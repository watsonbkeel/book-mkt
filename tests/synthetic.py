"""Synthetic evidence and deterministic model used by offline state-machine tests."""
import time,json
from outreach.profiles import digest
TEXT='Example Reader designs practical workflow tools for small teams and teaches adults how to check source evidence.'
BODY=('Your work on practical workflow tools suggests a useful setting for exploring how AI can help build something checkable. '
      'Use AI to Direct AI, published on Amazon, describes planning with one AI and using its written brief to direct other AIs to build and check a result. '
      'You keep the important decisions rather than handing over the whole task. '
      'For example, you could use this approach to sketch a small tool and define what would count as working before building it. '
      'Would a relevant chapter recommendation be useful for a project you have in mind?')
def seed(store,cid):
    sid='synthetic-'+str(cid)
    store.execute('INSERT OR IGNORE INTO evidence_sources(id,contact_id,url,retrieved_at,page_hash,text,content_hash) VALUES(?,?,?,?,?,?,?)',(sid,cid,'https://example.com/about',time.time(),digest(TEXT),TEXT,digest(TEXT)))
    contact=store.contact(cid);evidence=json.loads(contact['evidence_json'] or '{}')
    evidence.update(verification_version=3,profile_match={'status':'matched','quote':TEXT,'source_url':'https://example.com/about','reason':'Synthetic exact source evidence.'},
                    qualification={'status':'contactable','reasons':[]})
    store.update_contact(cid,evidence_json=json.dumps(evidence),verified_at=contact['verified_at'] or time.time())
    return store.one('SELECT * FROM evidence_sources WHERE id=?',(sid,))
def verdict(approved=True):
    return {'approved':approved,'hard_failures':[] if approved else ['Unsupported statement'], 'reason':'Synthetic check' if approved else 'Correct unsupported statement','quality':dict(relevance=4,specificity=4,naturalness=4,reply_burden=4)}
def full_copy(rows,body=BODY,subject='An AI planning idea for practical tools'):
    return dict(subject=subject,body=body,recipient_claims=[dict(statement='Builds workflow tools',source_id=rows[0]['id'],quote=rows[0]['text'])],book_fact_ids=['title','publication','method'],selected_chapter_ids=[10],offered_next_step='chapter_recommendation',asset_id=None,asset_version=None)
class SyntheticAI:
    def brief(self,contact,rows):return dict(verified_facts=[dict(statement='Builds practical tools',source_id=rows[0]['id'],quote=rows[0]['text'])],relevant_work_topic='practical workflow tools',possible_use_cases=['Could sketch a small tool'],unknowns=['Current projects'])
    def initial_copy(self,contact,brief=None,revision_feedback=''):return full_copy(brief['sources'])
    def review_initial(self,*args):return verdict(getattr(self,'approved',True))
    def review_reply(self,*args):return verdict(getattr(self,'approved',True))
    def reply_copy(self,context):
        body='Chapter 15 may help with your question about a concrete project. It describes keeping evidence separate from decisions when working with source materials. The book is published on Amazon: https://www.amazon.com/dp/B0HK4KMQF4'
        return dict(subject='Re: Book question',body=body,recipient_claims=[],book_fact_ids=['chapters','publication'],selected_chapter_ids=[15],offered_next_step='none',asset_id=None,asset_version=None)
