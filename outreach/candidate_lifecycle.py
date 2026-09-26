"""Expire pending work without erasing evidence or granting contact permission."""
import json
import time

PENDING_LIMIT = 2000


def active_pool_size(store):
    """Pending, ready and queued prospects share one capacity; history is retained separately."""
    return store.all("SELECT COUNT(*) n FROM contacts WHERE historical=0 AND state IN ('candidate','ready','queued')")[0]['n']


def archive_expired(store, max_age_days, now=None):
    now = time.time() if now is None else now
    cutoff = now - max_age_days * 86400
    archived = []
    with store.tx() as db:
        rows = db.execute("""SELECT c.*, MAX(c.created_at, COALESCE(c.verified_at,0),
            COALESCE((SELECT MAX(retrieved_at) FROM evidence_sources s WHERE s.contact_id=c.id),0)) AS basis
            FROM contacts c WHERE c.state IN ('candidate','ready','queued') AND c.historical=0
            AND (c.state='candidate' OR NOT EXISTS(
                SELECT 1 FROM messages m WHERE m.contact_id=c.id AND m.direction='outbound'
                AND (m.attempt_at IS NOT NULL OR m.state IN ('accepted','sending','uncertain'))))""").fetchall()
        for row in rows:
            if row['basis'] > cutoff:
                continue
            try:
                evidence = json.loads(row['evidence_json'])
            except (ValueError, TypeError):
                evidence = {}
            if not isinstance(evidence, dict):
                evidence = {}
            # Audit is durable across explicit re-verification; permission is never modified.
            archive = {'at': now, 'reason': 'pending_evidence_expired' if row['state']=='candidate' else 'uncontacted_evidence_expired', 'basis_at': row['basis'],
                       'max_age_days': max_age_days, 'previous_state': row['state']}
            evidence['archive'] = archive
            db.execute("UPDATE contacts SET state='archived',evidence_json=?,updated_at=? WHERE id=?",
                       (json.dumps(evidence, ensure_ascii=False), now, row['id']))
            db.execute("""UPDATE messages SET state='held',error='候选已过期归档，须重新核验'
                WHERE contact_id=? AND direction='outbound' AND state IN ('draft','queued') AND attempt_at IS NULL""", (row['id'],))
            db.execute("""UPDATE jobs SET state='failed',result='候选已过期归档，须重新核验',finished_at=?
                WHERE state='queued' AND kind IN ('draft','redraft','recheck','create_asset','send_once')
                AND (json_extract(payload,'$.contact_id')=? OR json_extract(payload,'$.message_id') IN
                (SELECT id FROM messages WHERE contact_id=?))""", (now, row['id'], row['id']))
            db.execute('INSERT INTO audit(event,detail,created_at) VALUES(?,?,?)',
                       ('candidate_archived', json.dumps({'contact_id': row['id'], **archive}), now))
            archived.append(row['id'])
    return archived
