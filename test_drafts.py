import re
from website import create_app, db
from website.models import User, ClinicalCase
from werkzeug.security import generate_password_hash

app = create_app('sqlite:///:memory:'); app.config['TESTING'] = True
def make_user(email, role):
    kw = dict(email=email, password=generate_password_hash('secret1'),
              first_name=email[0].upper(), role=role, is_approved=True)
    # Columns that may be required in your User model: fill them whenever they exist,
    # so this test keeps working if you add more required profile fields.
    if hasattr(User, 'last_name'):
        kw['last_name'] = 'Tester'
    if hasattr(User, 'medical_license'):
        kw['medical_license'] = 'LIC-' + email.split('@')[0]      # unique per user, in case it is UNIQUE
    return User(**kw)

with app.app_context():
    for email, role in [('a@x.com','doctor'),('b@x.com','doctor'),('admin@x.com','admin')]:
        db.session.add(make_user(email, role))
    db.session.commit()

def client(email):
    c = app.test_client(); c.post('/login', data={'email': email, 'password': 'secret1'}); return c
A, B, ADMIN = client('a@x.com'), client('b@x.com'), client('admin@x.com')
ok = lambda name, cond: print(('PASS ' if cond else 'FAIL ') + name) or cond
results = []
def check(name, cond): results.append(ok(name, bool(cond)))

FULL = dict(medical_condition='CLL', yob='1960', gender='M', current_adverse_event='Neutropenia',
            grade_of_current_adverse_event='3', type_of_current_treatment='Ibrutinib',
            description='clinical text', ongoing_treatment='on', priority='urgent')

# 1. save a nearly-empty draft
r = A.post('/', data={'action':'save_draft','medical_condition':'Half-filled CLL','yob':'1955'})
check('save_draft redirects to dashboard', r.status_code == 302 and r.location.endswith('/dashboard'))
with app.app_context():
    d = ClinicalCase.query.one(); draft_id = d.id
    check('draft stored with status=draft', d.status == 'draft')
    check('yob is actually persisted now (was silently lost before)', d.yob == 1955)

# 2. draft without a title is rejected (and doesn't crash)
r = A.post('/', data={'action':'save_draft'}, follow_redirects=True)
check('draft w/o diagnosis -> error message', b'Give the draft a diagnosis' in r.data)
with app.app_context(): check('...and nothing extra saved', ClinicalCase.query.count() == 1)

# 3. dashboard shows draft panel
r = A.get('/dashboard')
check('dashboard lists the draft', b'Half-filled CLL' in r.data and b'drafts-panel' in r.data)
check('draft NOT in History/Archive list', r.data.count(b'Half-filled CLL') == 1)

# 4. edit page is prefilled
r = A.get(f'/draft/{draft_id}')
check('edit form prefilled (condition + yob)', b'value="Half-filled CLL"' in r.data and b'value="1955"' in r.data)
check('edit form says Edit Draft / Submit Draft', b'Edit Draft' in r.data and b'Submit Draft' in r.data)

# 5. submitting an incomplete draft is refused and stays a draft
r = A.post(f'/draft/{draft_id}', data={'action':'submit','medical_condition':'Half-filled CLL','yob':'1955'}, follow_redirects=True)
check('incomplete submit rejected with list of missing fields', b'Please complete' in r.data and b'Treatment type' in r.data)
check('typed values survive the failed submit', b'value="Half-filled CLL"' in r.data)
with app.app_context(): check('still a draft', db.session.get(ClinicalCase, draft_id).status == 'draft')

# 6. privacy: other doctor and admin cannot see/touch it
check('other doctor: edit -> 404', B.get(f'/draft/{draft_id}').status_code == 404)
check('other doctor: delete -> 404', B.post(f'/draft/{draft_id}/delete').status_code == 404)
check('other doctor: case view -> 404', B.get(f'/case/{draft_id}').status_code == 404)
check('admin: case view -> 404', ADMIN.get(f'/case/{draft_id}').status_code == 404)
check('admin dashboard does not list it', b'Half-filled CLL' not in ADMIN.get('/dashboard').data)
check('admin archive does not list it', b'Half-filled CLL' not in ADMIN.get('/archive').data)
check('admin cannot create via draft route', ADMIN.get(f'/draft/{draft_id}').status_code in (403, 404))

# 7. complete + submit the draft
r = A.post(f'/draft/{draft_id}', data={**FULL, 'action':'submit'}, follow_redirects=False)
check('submit draft redirects', r.status_code == 302)
with app.app_context():
    c = db.session.get(ClinicalCase, draft_id)
    check('status flipped to submitted (same row, no duplicate)', c.status == 'submitted' and ClinicalCase.query.count() == 1)
    check('priority + typed columns saved', c.priority == 'urgent' and c.grade_of_current_adverse_event == 3)
check('draft panel now empty', b'No drafts.' in A.get('/dashboard').data)
check('admin now sees it', b'CLL' in ADMIN.get('/dashboard').data or b'CLL' in ADMIN.get('/archive').data)
check('submitted case can no longer be opened as draft', A.get(f'/draft/{draft_id}').status_code == 404)

# 8. direct submit (no draft) and a delete
r = A.post('/', data={**FULL, 'action':'submit', 'medical_condition':'Direct'})
check('direct submit works (was an IntegrityError before)', r.status_code == 302)
A.post('/', data={'action':'save_draft','medical_condition':'To delete'})
with app.app_context(): del_id = ClinicalCase.query.filter_by(medical_condition='To delete').one().id
A.post(f'/draft/{del_id}/delete')
with app.app_context(): check('draft deleted', db.session.get(ClinicalCase, del_id) is None)

# 9. hostile / bad input must not 500
r = A.post('/', data={'action':'save_draft','medical_condition':'x','yob':'abc','grade_of_current_adverse_event':'99','date_of_current_treatment':'not-a-date','priority':'<script>'}, follow_redirects=True)
check('bad input -> friendly errors, no 500', r.status_code == 200 and b'whole number' in r.data and b'not a valid date' in r.data)
r = A.post('/', data={**FULL, 'action':'submit', 'ongoing_treatment': None}, follow_redirects=True)
check('not-ongoing treatment requires interruption date', b'interruption' in r.data.lower())

check('admin can open / (home page)', ADMIN.get('/').status_code == 200)
check('admin cannot POST a case', ADMIN.post('/', data={**FULL,'action':'submit'}).status_code == 403)
# 9b. feedback / internal chat (the form posts action_type=add_reply)
from website.models import Reply
cid = FULL_ID = None
with app.app_context(): cid = ClinicalCase.query.filter_by(status='submitted').first().id
A.post(f'/case/{cid}', data={'action_type':'add_reply','reply_text':'Author feedback text'})
ADMIN.post(f'/case/{cid}', data={'action_type':'add_reply','reply_text':'Admin feedback text'})
with app.app_context():
    texts = [r.reply_text for r in Reply.query.filter_by(case_id=cid).all()]
    check('author feedback saved', 'Author feedback text' in texts)
    check('admin feedback saved', 'Admin feedback text' in texts)
    check('feedback stored as internal', all(r.is_internal for r in Reply.query.filter_by(case_id=cid).all()))
check('feedback shows on the case page', b'Admin feedback text' in A.get(f'/case/{cid}').data)
r = A.post(f'/case/{cid}', data={'action_type':'add_reply','reply_text':'hi'}, follow_redirects=True)
check('too-short feedback rejected', b'at least 5 characters' in r.data)
B.post(f'/case/{cid}', data={'action_type':'add_reply','reply_text':'Stranger tries to post'})
with app.app_context(): check('other doctor cannot post feedback', 'Stranger tries to post' not in [r.reply_text for r in Reply.query.all()])
# 9c. ACCEPTED = closed & solved: every user sees it in Closed Cases (dashboard) and Approved (archive)
import re as _re
def closed_count(client):
    html = client.get('/dashboard').data.decode()
    return int(_re.search(r'Closed Cases</h6>\s*<h3[^>]*>(\d+)</h3>', html).group(1))
def approved_pane(client):
    html = client.get('/archive').data.decode()
    pane = html.split('id="approved_pane"')[1].split('id="rejected_pane"')[0]
    return pane
def mk(title):
    A.post('/', data={**FULL, 'action':'submit', 'medical_condition': title})
    with app.app_context(): return ClinicalCase.query.filter_by(medical_condition=title).one().id
acc, rej, pend = mk('ACCEPTED-CASE'), mk('REJECTED-CASE'), mk('PENDING-CASE')
ADMIN.post(f'/case/{acc}',  data={'action_type':'triage_action','status':'accept'})
ADMIN.post(f'/case/{rej}',  data={'action_type':'triage_action','status':'reject'})
base_before = closed_count(B)
check('closed count is 1 for a stranger doctor (not the author)', base_before == 1)
check('closed count equal for author, stranger and admin', closed_count(A) == closed_count(B) == closed_count(ADMIN) == 1)
check('stranger sees accepted case in Approved panel', 'ACCEPTED-CASE' in approved_pane(B))
check('author sees it in Approved panel', 'ACCEPTED-CASE' in approved_pane(A))
check('admin sees it in Approved panel', 'ACCEPTED-CASE' in approved_pane(ADMIN))
check('stranger can open the accepted case', B.get(f'/case/{acc}').status_code == 200)
check('pending case NOT in Approved panel', 'PENDING-CASE' not in approved_pane(B))
check('rejected case NOT in Approved panel', 'REJECTED-CASE' not in approved_pane(B) and 'REJECTED-CASE' not in approved_pane(ADMIN))
check('stranger cannot see someone elses pending case', B.get(f'/case/{pend}').status_code == 403)
A.post('/', data={'action':'save_draft','medical_condition':'DRAFT-NEVER-PUBLIC'})
check('drafts never appear as closed', 'DRAFT-NEVER-PUBLIC' not in approved_pane(B) and closed_count(B) == 1)
with app.app_context():
    c = db.session.get(ClinicalCase, acc); c.is_deleted = True; db.session.commit()
check('deleted accepted case disappears for everyone', closed_count(B) == 0 and 'ACCEPTED-CASE' not in approved_pane(A))
# 9d. internal feedback -> official statements
from website.models import AuditLog
oc = mk('OFFICIAL-CASE')
ADMIN.post(f'/case/{oc}', data={'action_type':'add_reply','reply_text':'ADMIN-INTERNAL-NOTE'})
A.post(f'/case/{oc}',     data={'action_type':'add_reply','reply_text':'DOCTOR-INTERNAL-NOTE'})
with app.app_context():
    adm_msg = Reply.query.filter_by(reply_text='ADMIN-INTERNAL-NOTE').one().id
    doc_msg = Reply.query.filter_by(reply_text='DOCTOR-INTERNAL-NOTE').one().id
ADMIN.post(f'/case/{oc}', data={'action_type':'triage_action','status':'accept'})   # accepted => B may open it

page = B.get(f'/case/{oc}').data.decode()
check('before publishing: stranger sees NO internal notes', 'ADMIN-INTERNAL-NOTE' not in page and 'DOCTOR-INTERNAL-NOTE' not in page)
check('before publishing: stranger sees the empty-state text', 'No official statement has been issued' in page)

check('author cannot publish (403)', A.post(f'/case/{oc}', data={'action_type':'publish_official','reply_id':adm_msg}).status_code == 403)
check('stranger cannot publish (403)', B.post(f'/case/{oc}', data={'action_type':'publish_official','reply_id':adm_msg}).status_code == 403)
with app.app_context(): check('still internal after refused attempts', db.session.get(Reply, adm_msg).is_internal is True)

ADMIN.post(f'/case/{oc}', data={'action_type':'publish_official','reply_id':adm_msg})
with app.app_context():
    r = db.session.get(Reply, adm_msg)
    check('admin message promoted (is_internal False, same author/text)', r.is_internal is False and r.reply_text == 'ADMIN-INTERNAL-NOTE')
    check('promotion is audit-logged', AuditLog.query.filter_by(action='PUBLISH_OFFICIAL_STATEMENT', target_case_id=oc).count() == 1)
page = B.get(f'/case/{oc}').data.decode()
official_html = page.split('id="official-statements"')[1]
check('stranger now sees it under Official Statements', 'ADMIN-INTERNAL-NOTE' in official_html)
check('stranger still cannot see the doctor note', 'DOCTOR-INTERNAL-NOTE' not in page)
check('stranger gets no internal-chat card', 'Feedback &amp; Internal Chat' not in page)
check('author sees official + their own internal chat', 'ADMIN-INTERNAL-NOTE' in A.get(f'/case/{oc}').data.decode() and 'Feedback &amp; Internal Chat' in A.get(f'/case/{oc}').data.decode())

ADMIN.post(f'/case/{oc}', data={'action_type':'publish_official','reply_id':doc_msg})
with app.app_context(): check('a DOCTOR message cannot be promoted', db.session.get(Reply, doc_msg).is_internal is True)
check('wrong reply id -> 404', ADMIN.post(f'/case/{oc}', data={'action_type':'publish_official','reply_id':99999}).status_code == 404)
other_case = mk('OTHER-CASE')
check('reply of another case -> 404', ADMIN.post(f'/case/{other_case}', data={'action_type':'publish_official','reply_id':doc_msg}).status_code == 404)

ADMIN.post(f'/case/{oc}', data={'action_type':'add_official','reply_text':'DIRECT-OFFICIAL-TEXT'})
check('admin can write an official statement directly', 'DIRECT-OFFICIAL-TEXT' in B.get(f'/case/{oc}').data.decode().split('id="official-statements"')[1])
check('doctor cannot write an official statement (403)', A.post(f'/case/{oc}', data={'action_type':'add_official','reply_text':'FAKE OFFICIAL'}).status_code == 403)
ADMIN.post(f'/case/{oc}', data={'action_type':'add_official','reply_text':'no'})
with app.app_context(): check('too-short official statement not saved', Reply.query.filter_by(reply_text='no').count() == 0)
check('unknown action -> 400 (no silent success)', ADMIN.post(f'/case/{oc}', data={'action_type':'bogus'}).status_code == 400)
# 9e. IGHV / del17p / TP53 are locked after submission
lk = None
A.post('/', data={**FULL, 'action':'submit', 'medical_condition':'LOCK-CASE', 'ighv':'Mutated', 'del17p':'Present', 'tp53':'Wild-type'})
with app.app_context(): lk = ClinicalCase.query.filter_by(medical_condition='LOCK-CASE').one().id
ADMIN.post(f'/case/{lk}', data={'action_type':'triage_action','status':'accept'})     # so the stranger may open it
def bio(): 
    with app.app_context():
        c = db.session.get(ClinicalCase, lk); return (c.ighv, c.del17p, c.tp53)
check('biomarkers saved as submitted', bio() == ('Mutated','Present','Wild-type'))
for who, cl in [('author', A), ('admin', ADMIN), ('other user', B)]:
    html = cl.get(f'/case/{lk}').data.decode()
    check(f'{who}: biomarkers shown read-only with the TRUE stored values',
          'id="ighv" data-locked="true">Mutated<' in html and 'id="del17p" data-locked="true">Present<' in html and 'id="tp53" data-locked="true">Wild-type<' in html)
    check(f'{who}: no editable dropdown for the three biomarkers',
          not any(f'id="{n}"' in html and f'<select' in html.split(f'id="{n}"')[1][:5] for n in ('ighv','del17p','tp53')) and 'name="ighv"' not in html)
    check(f'{who}: page says it is locked', 'Locked after submission' in html)

tamper = {'ighv':'Unmutated', 'del17p':'Absent', 'tp53':'Mutated'}
for who, cl in [('author', A), ('admin', ADMIN), ('other user', B)]:
    for act in ['add_reply', 'triage_action', 'update_status', 'update_assignment', 'add_official']:
        cl.post(f'/case/{lk}', data={'action_type': act, 'reply_text':'tamper attempt', 'status':'accept', **tamper})
    check(f'{who}: tampering through every case action changes nothing', bio() == ('Mutated','Present','Wild-type'))
check('author cannot reopen submitted case as a draft (404)', A.post(f'/draft/{lk}', data={**FULL, 'action':'save_draft', **tamper}).status_code == 404)
check('...and nothing changed', bio() == ('Mutated','Present','Wild-type'))

with app.app_context():                      # the data layer itself refuses, whatever the caller
    c = db.session.get(ClinicalCase, lk); c.ighv = 'Unmutated'
    try: db.session.commit(); refused = False
    except ValueError: db.session.rollback(); refused = True
    check('database layer rejects a direct change to a submitted case', refused)
    c = db.session.get(ClinicalCase, lk); c.description = 'non-locked field edit is fine'; db.session.commit()
    check('other fields of a submitted case are not blocked by the lock', db.session.get(ClinicalCase, lk).description == 'non-locked field edit is fine')

# drafts stay fully editable, and the draft -> submitted transition may still set the values
A.post('/', data={'action':'save_draft','medical_condition':'LOCK-DRAFT','tp53':'Mutated'})
with app.app_context(): ld = ClinicalCase.query.filter_by(medical_condition='LOCK-DRAFT').one().id
A.post(f'/draft/{ld}', data={'action':'save_draft','medical_condition':'LOCK-DRAFT','tp53':'Wild-type','ighv':'Unmutated'})
with app.app_context(): d = db.session.get(ClinicalCase, ld); check('draft biomarkers are editable', (d.tp53, d.ighv) == ('Wild-type','Unmutated'))
A.post(f'/draft/{ld}', data={**FULL, 'action':'submit', 'medical_condition':'LOCK-DRAFT', 'tp53':'Mutated', 'ighv':'Unmutated', 'del17p':'Absent'})
with app.app_context():
    d = db.session.get(ClinicalCase, ld)
    check('final edit during submit is accepted, then locked', d.status == 'submitted' and (d.tp53, d.ighv, d.del17p) == ('Mutated','Unmutated','Absent'))
    d.tp53 = 'Wild-type'
    try: db.session.commit(); refused = False
    except ValueError: db.session.rollback(); refused = True
    check('after submission the same field is locked', refused)
# 10. other pages still render
for url in ['/dashboard','/archive']:
    check(f'GET {url} 200 for doctor', A.get(url).status_code == 200)
check('GET /sign-up renders', app.test_client().get('/sign-up').status_code == 200)

print(f'\n{sum(results)}/{len(results)} passed')
