import pytest
# Original transport/rate-limit tests now need the explicit evidence prerequisite.
# Their model fakes inherit SyntheticAI; new contract/evidence tests seed explicitly.
LEGACY_PIPELINE_TESTS={'test_mail_engine.py','test_worker_flow.py','test_ai_review_send.py','test_v11_regressions.py','test_v11_boundaries.py','test_v11_final_review.py','test_v12_final_review.py'}
@pytest.fixture(autouse=True)
def legacy_synthetic_sources(request,monkeypatch):
    if request.path.name not in LEGACY_PIPELINE_TESTS:return
    from outreach.db import Store
    from synthetic import seed
    original=Store.add_contact
    def add(self,**kwargs):
        cid=original(self,**kwargs)
        if kwargs.get('eligibility')=='consent':seed(self,cid)
        return cid
    monkeypatch.setattr(Store,'add_contact',add)

@pytest.fixture(autouse=True)
def no_external_connections(monkeypatch):
    import socket
    def denied(*args,**kwargs):raise AssertionError('Test attempted a real socket connection; use a mock')
    monkeypatch.setattr(socket,'create_connection',denied)
