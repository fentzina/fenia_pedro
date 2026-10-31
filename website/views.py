from datetime import datetime, date, timezone
from flask import Blueprint, render_template, request, flash, redirect, url_for, abort
from flask_login import login_required, current_user
from .models import AuditLog, ClinicalCase, Reply, User, CASE_STATUS_DRAFT, CASE_STATUS_SUBMITTED
from . import db

views = Blueprint('views', __name__)

def abort_if_not_admin():
    if current_user.role != 'admin':
        abort(403)

def log_audit_action(action_name, case_id=None):
    log = AuditLog(user_id=current_user.id, action=action_name, target_case_id=case_id)
    db.session.add(log)
    db.session.commit()


# ---------------------------------------------------------------------------
# Case form handling (shared by "new case" and "edit draft")
# ---------------------------------------------------------------------------
TEXT_FIELDS = [
    'medical_condition', 'gender', 'current_adverse_event', 'comorbidities',
    'type_of_current_treatment', 'dose_of_current_treatment',
    'descr_of_current_treatment', 'concomitant_medication',
    'karyotype_treatment', 'description',
]
INT_FIELDS = {   # field name -> (label, min, max)
    'yob': ('Year of birth', 1900, datetime.now().year),
    'grade_of_current_adverse_event': ('Grade', 1, 5),
    'cycle_of_current_adverse_event': ('Treatment cycle', 1, 100),
    'days_since_current_adverse_event': ('Days since onset', 0, 3650),
    'current_line_of_treatment': ('Line of treatment', 1, 20),
}
DATE_FIELDS = {
    'date_of_current_treatment': 'Date of treatment start',
    'date_of_treatment_interuption': 'Date of treatment interruption',
}
BOOL_FIELDS = ['previous_adverse_event', 'ongoing_treatment']
CHOICES = {
    'ighv': ['Unknown', 'Mutated', 'Unmutated'],
    'del17p': ['Unknown', 'Present', 'Absent'],
    'tp53': ['Unknown', 'Mutated', 'Wild-type'],
    'priority': ['routine', 'urgent', 'high'],
}
# What a doctor MUST have filled in before a case can be submitted.
# (A draft only needs medical_condition - see _handle_case_form.)
REQUIRED_FOR_SUBMISSION = {
    'medical_condition': 'Diagnosis / Disease',
    'yob': 'Year of birth',
    'gender': 'Biological gender',
    'current_adverse_event': 'Current adverse event',
    'grade_of_current_adverse_event': 'Grade',
    'type_of_current_treatment': 'Treatment type',
    'description': 'Clinical description',
}


def parse_case_form(form):
    """Turn raw request.form strings into typed values. Returns (data, errors).
    Never raises: bad input becomes an error message instead of a 500."""
    data, errors = {}, []

    for name in TEXT_FIELDS:
        data[name] = (form.get(name) or '').strip() or None

    for name, (label, lo, hi) in INT_FIELDS.items():
        raw = (form.get(name) or '').strip()
        if not raw:
            data[name] = None
            continue
        try:
            value = int(raw)
        except ValueError:
            errors.append(f'{label} must be a whole number.')
            data[name] = None
            continue
        if not lo <= value <= hi:
            errors.append(f'{label} must be between {lo} and {hi}.')
            value = None
        data[name] = value

    for name, label in DATE_FIELDS.items():
        raw = (form.get(name) or '').strip()
        try:
            data[name] = date.fromisoformat(raw) if raw else None
        except ValueError:
            errors.append(f'{label} is not a valid date.')
            data[name] = None

    for name in BOOL_FIELDS:                 # an unchecked checkbox is simply absent from the POST
        data[name] = name in form

    for name, allowed in CHOICES.items():    # whitelist: never trust a <select> value
        raw = form.get(name)
        data[name] = raw if raw in allowed else allowed[0]

    return data, errors


def missing_for_submission(data):
    missing = [label for field, label in REQUIRED_FOR_SUBMISSION.items() if not data.get(field)]
    if not data.get('ongoing_treatment') and not data.get('date_of_treatment_interuption'):
        missing.append('Date of treatment interruption')
    return missing


def case_to_form_values(case):
    """Reverse of parse_case_form: DB object -> dict of strings the template can print."""
    values = {}
    for name in TEXT_FIELDS + list(CHOICES) + list(INT_FIELDS) + list(DATE_FIELDS):
        v = getattr(case, name)
        values[name] = '' if v is None else (v.isoformat() if isinstance(v, date) else str(v))
    for name in BOOL_FIELDS:
        if getattr(case, name):
            values[name] = 'on'
    return values


def _handle_case_form(case=None):
    """One code path for creating a case and for editing a draft.
    `case` is None for a brand-new case, or an existing draft being edited."""
    if current_user.role == 'admin':                 # admins triage cases, they don't author them
        if request.method == 'POST':
            abort(403)
        # GET: the template shows admins an info message instead of the form
        return render_template('home.html', user=current_user, f={}, editing=None,
                               current_year=datetime.now().year)

    if request.method == 'POST':
        saving_draft = request.form.get('action') == 'save_draft'
        data, errors = parse_case_form(request.form)

        if saving_draft:
            if not data['medical_condition']:
                errors.append('Give the draft a diagnosis so you can recognise it later.')
        else:
            missing = missing_for_submission(data)
            if missing:
                errors.append('Please complete: ' + ', '.join(missing) + '.')

        if errors:
            for e in errors:
                flash(e, category='error')
            # re-render with what the user typed instead of an empty form
            return render_template('home.html', user=current_user, f=request.form,
                                   editing=case, current_year=datetime.now().year)

        was_draft = case is not None
        if case is None:
            case = ClinicalCase(user_id=current_user.id)
            db.session.add(case)
        for name, value in data.items():
            setattr(case, name, value)
        case.status = CASE_STATUS_DRAFT if saving_draft else CASE_STATUS_SUBMITTED
        if not saving_draft:
            case.date_created = datetime.now(timezone.utc)   # "Submitted on" = moment of submission
        db.session.commit()

        if saving_draft:
            log_audit_action('SAVE_CASE_DRAFT', case.id)
            flash('Draft saved. You can finish it later from your dashboard.', category='success')
        else:
            log_audit_action('SUBMIT_DRAFT' if was_draft else 'CREATE_CLINICAL_CASE', case.id)
            flash('Your case has been submitted successfully!', category='success')
        return redirect(url_for('views.dashboard'))

    form_values = case_to_form_values(case) if case else {'ongoing_treatment': 'on', 'priority': 'routine'}
    return render_template('home.html', user=current_user, f=form_values,
                           editing=case, current_year=datetime.now().year)


def closed_cases_query():
    """An ACCEPTED case is closed and solved: it is published, so EVERY logged-in user
    (doctor or admin, author or not) may see it. Drafts, rejected and deleted cases never match."""
    return ClinicalCase.query.filter_by(
        status=CASE_STATUS_SUBMITTED, priority='accept', is_deleted=False
    )

@views.route('/', methods=['GET', 'POST'])
@login_required
def home():
    return _handle_case_form()


@views.route('/draft/<int:case_id>', methods=['GET', 'POST'])
@login_required
def edit_draft(case_id):
    # Scoped by owner AND status in the query itself: someone else's draft, or an
    # already-submitted case, is simply "not found" (404) rather than "forbidden".
    draft = ClinicalCase.query.filter_by(
        id=case_id, user_id=current_user.id, status=CASE_STATUS_DRAFT, is_deleted=False
    ).first_or_404()
    return _handle_case_form(draft)


@views.route('/draft/<int:case_id>/delete', methods=['POST'])
@login_required
def delete_draft(case_id):
    draft = ClinicalCase.query.filter_by(
        id=case_id, user_id=current_user.id, status=CASE_STATUS_DRAFT
    ).first_or_404()
    log_audit_action('DELETE_CASE_DRAFT', draft.id)
    db.session.delete(draft)          # a draft was never sent to anyone: safe to hard-delete
    db.session.commit()
    flash('Draft deleted.', category='info')
    return redirect(url_for('views.dashboard'))

# Dashboard
# @views.route('/dashboard')
# @login_required
# def dashboard():
#     total_uploaded = ClinicalCase.query.filter_by(user_id=current_user.id).count()
#     user_approved = ClinicalCase.query.filter_by(user_id=current_user.id, priority='approved', is_deleted=False).count()
#     user_rejected = ClinicalCase.query.filter_by(user_id=current_user.id, priority='rejected', is_deleted=False).count()
#     user_drafts = ClinicalCase.query.filter_by(user_id=current_user.id, is_deleted=False).filter(ClinicalCase.priority.in_(['routine', 'urgent', 'high'])).count()
#     user_deleted = ClinicalCase.query.filter_by(user_id=current_user.id, is_deleted=True).count()

#     # Αν είναι Admin, βλέπει και τα γενικά metrics του συστήματος
#     system_metrics = {}
#     if current_user.role == 'admin':
#         system_metrics['total_users'] = User.query.count()
#         system_metrics['pending_cases'] = ClinicalCase.query.filter_by(is_deleted=False).filter(ClinicalCase.priority.in_(['routine', 'urgent', 'high'])).count()

#     return render_template("dashboard.html", user=current_user, total=total_uploaded, approved=user_approved, rejected=user_rejected, drafts=user_drafts, deleted=user_deleted, system=system_metrics)

@views.route('/dashboard')
@login_required
def dashboard():
    # Drafts are private to their author, so every shared/admin query below is
    # restricted to status == 'submitted'.
    submitted = ClinicalCase.query.filter_by(status=CASE_STATUS_SUBMITTED)
    closed = closed_cases_query().count()      # same number for every user: closed cases are public

    if current_user.role == 'admin':
        total_triage = submitted.filter(ClinicalCase.priority.in_(['routine', 'urgent', 'high'])).count()
        total_resolved = submitted.filter_by(priority='resolved').count()
        cases = submitted.order_by(ClinicalCase.date_created.desc()).all()
        return render_template("dashboard.html", user=current_user, cases=cases, drafts=[],
                               triage=total_triage, closed=closed, resolved=total_resolved)

    mine = submitted.filter_by(user_id=current_user.id)
    my_triage = mine.filter(ClinicalCase.priority.in_(['routine', 'urgent', 'high'])).count()
    my_resolved = mine.filter_by(priority='resolved').count()
    my_cases = mine.order_by(ClinicalCase.date_created.desc()).all()

    my_drafts = (ClinicalCase.query
                 .filter_by(user_id=current_user.id, status=CASE_STATUS_DRAFT, is_deleted=False)
                 .order_by(ClinicalCase.updated_at.desc())
                 .all())
    return render_template("dashboard.html", user=current_user, cases=my_cases, drafts=my_drafts,
                           triage=my_triage, closed=closed, resolved=my_resolved)


@views.route('/case/<int:case_id>', methods=['GET', 'POST'])
@login_required
def case_details(case_id):
    case = ClinicalCase.query.get_or_404(case_id)

    is_admin = current_user.role == 'admin'
    is_author = case.user_id == current_user.id

    # A draft has not been sent to anyone yet: only its author may open it (and gets the edit form).
    if case.status == CASE_STATUS_DRAFT:
        if is_author:
            return redirect(url_for('views.edit_draft', case_id=case.id))
        abort(404)

    # Ένας γιατρός βλέπει το case ΜΟΝΟ αν είναι ο δημιουργός του Ή αν το case έχει γίνει 'accept' (δημοσιευμένο)
    if not (is_admin or is_author or case.priority == 'accept'):
        log_audit_action('UNAUTHORIZED_ACCESS_ATTEMPT', case.id)
        abort(403)

    if request.method == 'POST':
        action_type = request.form.get('action_type')

        # 'add_reply' is the name the case_details.html feedback form actually posts
        if action_type in ('add_internal_message', 'add_reply'):
            if not (is_admin or is_author):
                flash('You are not allowed to access this discussion.', category='error')
                return redirect(url_for('views.case_details', case_id=case.id))

            reply_text = (request.form.get('reply_text') or '').strip()
            if len(reply_text) >= 5:
                new_message = Reply(reply_text=reply_text, case_id=case.id, user_id=current_user.id, is_internal=True)
                db.session.add(new_message)
                db.session.commit()
                log_audit_action('ADD_CASE_FEEDBACK', case.id)
                flash('The internal message was added!', category='success')
            else:
                flash('Your message must be at least 5 characters long.', category='error')
            return redirect(url_for('views.case_details', case_id=case.id))

        elif action_type == 'publish_official':
            # Promote an EXISTING internal message to an official statement (same row: author,
            # text and timestamp are preserved, so provenance is intact).
            if not is_admin:
                abort(403)
            reply = Reply.query.filter_by(id=request.form.get('reply_id', type=int), case_id=case.id).first_or_404()
            if not reply.is_internal:
                flash('That message is already an official statement.', category='info')
            elif not (reply.author and reply.author.role == 'admin'):
                # an official statement is an expert opinion; a doctor's message is case information
                flash('Only messages written by an admin/expert can be published as official statements.', category='error')
            else:
                reply.is_internal = False
                db.session.commit()
                log_audit_action('PUBLISH_OFFICIAL_STATEMENT', case.id)
                flash('The message is now an official statement.', category='success')
            return redirect(url_for('views.case_details', case_id=case.id))

        elif action_type == 'add_official':
            # Write a brand-new official statement directly (no internal draft needed).
            if not is_admin:
                abort(403)
            reply_text = (request.form.get('reply_text') or '').strip()
            if len(reply_text) >= 5:
                db.session.add(Reply(reply_text=reply_text, case_id=case.id, user_id=current_user.id, is_internal=False))
                db.session.commit()
                log_audit_action('ADD_OFFICIAL_STATEMENT', case.id)
                flash('Official statement published.', category='success')
            else:
                flash('An official statement must be at least 5 characters long.', category='error')
            return redirect(url_for('views.case_details', case_id=case.id))

        elif action_type == 'triage_action':
            if not is_admin:
                abort(403)

            new_status = request.form.get('status')
            raw_admin_id = request.form.get('assigned_admin_id')

            if new_status in ['routine', 'urgent', 'high', 'accept', 'reject']:
                case.priority = new_status

            if raw_admin_id and raw_admin_id.strip() != "":
                case.assigned_admin_id = int(raw_admin_id)
            else:
                case.assigned_admin_id = None

            db.session.commit()
            flash('Saved!', category='success')
            return redirect(url_for('views.archive'))

        elif action_type == 'soft_delete_case':
            if not is_author:
                abort(403)
            case.hidden_by_author = True
            db.session.commit()
            log_audit_action('SOFT_DELETE_CASE_BY_AUTHOR', case.id)
            flash('The case was removed from your dashboard.', category='info')
            return redirect(url_for('views.dashboard'))

        elif action_type == 'submit_final_draft':
            if not is_admin: abort(403)
            case.priority = 'board_review'
            db.session.commit()
            flash('The case was submitted for board review!', category='success')
            return redirect(url_for('views.dashboard'))

        elif action_type == 'resolve_case':
            if not is_admin: abort(403)
            reply_text = request.form.get('reply_text')
            if reply_text and len(reply_text.strip()) >= 5:
                final_reply = Reply(reply_text=reply_text, case_id=case.id, user_id=current_user.id, is_internal=False)
                case.priority = 'resolved'
                db.session.add(final_reply)
                db.session.commit()
                flash('The case was resolved and the official opinion was issued!', category='success')
            else:
                flash('Please write the official opinion before closing the case.', category='error')
            return redirect(url_for('views.dashboard'))

        elif action_type == 'reopen_case':
            if not is_author: abort(403)
            case.priority = 'urgent' # Επαναφορά σε επείγουσα διαλογή
            db.session.commit()
            flash('This case was reopened due to new clinical data!', category='success')
            return redirect(url_for('views.case_details', case_id=case.id))

        elif is_admin and action_type in ('update_status', 'update_assignment'):
            if action_type == 'update_status':
                case.priority = request.form.get('status')
            elif action_type == 'update_assignment':
                admin_id = request.form.get('assigned_admin_id')
                case.assigned_admin_id = int(admin_id) if admin_id else None

            db.session.commit()
            flash('Updated successfully!', category='success')
            return redirect(url_for('views.case_details', case_id=case.id))

        else:
            abort(400)      # unknown action: fail loudly instead of silently doing nothing

    log_audit_action('VIEW_CASE_DETAILS', case.id)

    # Admins και ο δημιουργός βλέπουν όλη την αλληλογραφία· οι υπόλοιποι ΜΟΝΟ τις επίσημες γνωμοδοτήσεις
    replies_query = Reply.query.filter_by(case_id=case.id)
    if not (is_admin or is_author):
        replies_query = replies_query.filter_by(is_internal=False)
    replies = replies_query.order_by(Reply.date_created.asc()).all()
    official_replies = [r for r in replies if not r.is_internal]
    internal_replies = [r for r in replies if r.is_internal]      # empty for everyone except admin/author

    all_admins = User.query.filter_by(role='admin').all()

    return render_template("case_details.html", user=current_user, case=case, admins=all_admins,
                           replies=replies, official_replies=official_replies, internal_replies=internal_replies)

# Soft Delete case από τον Γιατρό
@views.route('/delete-case/<int:case_id>')
@login_required
def delete_case(case_id):
    case = ClinicalCase.query.get_or_404(case_id)
    if case.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
    case.is_deleted = True
    db.session.commit()
    flash('Case was erased from the feed.', category='info')
    return redirect(url_for('views.dashboard'))

# Soft Delete Filters
# @views.route('/archive')
# @login_required
# def archive():
#     abort_if_not_admin()
#     drafts = ClinicalCase.query.filter_by(is_deleted=False).filter(ClinicalCase.priority.in_(['routine', 'urgent', 'high'])).all()
#     approved = ClinicalCase.query.filter_by(priority='approved', is_deleted=False).all()
#     rejected = ClinicalCase.query.filter_by(priority='rejected', is_deleted=False).all()
#     return render_template("archive.html", user=current_user, drafts=drafts, approved=approved, rejected=rejected)

@views.route('/archive')
@login_required
def archive():
    base = ClinicalCase.query.filter_by(status=CASE_STATUS_SUBMITTED)   # never show drafts here
    if current_user.role != 'admin':
        base = base.filter_by(user_id=current_user.id)   # pending / rejected: only your own

    # NOTE: "drafts" in this page means "waiting for triage", NOT the author's unsent drafts.
    drafts_cases = base.filter(ClinicalCase.priority.in_(['routine', 'urgent', 'high'])).all()
    approved_cases = closed_cases_query().order_by(ClinicalCase.date_created.desc()).all()   # everyone sees these
    rejected_cases = base.filter_by(priority='reject').all()

    return render_template("archive.html", user=current_user,
                           drafts=drafts_cases, approved=approved_cases, rejected=rejected_cases)


@views.route('/user-management')
@login_required
def user_management():
    abort_if_not_admin()

    pending_users = User.query.filter_by(is_approved=False, role='doctor').all() # Φορτώνει τους χρήστες που εκκρεμούν προς έγκριση (Pending Doctors)
    
    # Φορτώνει ΜΟΝΟ όσους είναι εγκεκριμένοι γιατροί Ή είναι Admins
    # (!!!) Εξαιρω μόνο τον τρεχον συνδεδεμένο χρήστη για να μην αλλάξει κατά λάθος τον εαυτό του
    all_approved_and_admins = User.query.filter(
        (User.id != current_user.id) & 
        ((User.is_approved == True) | (User.role == 'admin'))
    ).all()
    
    return render_template(
        "user_management.html", 
        user=current_user, 
        pending_users=pending_users, 
        all_users=all_approved_and_admins
    )

@views.route('/change-role/<int:user_id>', methods=['POST'])
@login_required
def change_role(user_id):
    abort_if_not_admin()
    target_user = User.query.get_or_404(user_id)
    new_role = request.form.get('new_role')
    if new_role in ['doctor', 'admin']:
        target_user.role = new_role
        db.session.commit()
        flash(f'User {target_user.email} changed to {new_role.upper()}!', category='success')
    return redirect(url_for('views.user_management'))

@views.route('/action-user/<string:action>/<int:user_id>')
@login_required
def action_user(action, user_id):
    abort_if_not_admin()
    target_user = User.query.get_or_404(user_id)
    if action == 'approve':
        target_user.is_approved = True
        flash(f'Dr. {target_user.first_name} account got accepted!', category='success')
    elif action == 'reject':
        db.session.delete(target_user)
        flash(f'Your account request got rejected.', category='warning')
    db.session.commit()
    return redirect(url_for('views.user_management'))

# @views.route('/case/<int:case_id>', methods=['GET', 'POST'])
# @login_required
# def case_details(case_id):
#     case = ClinicalCase.query.get_or_404(case_id)
    
#     # Ένας γιατρός επιτρέπεται να δει το case ΜΟΝΟ αν είναι ο δημιουργός του Ή αν το case έχει εγκριθεί και δημοσιευτεί.
#     if current_user.role != 'admin' and case.user_id != current_user.id and case.priority != 'approved':
#         # Καταγραφή αποτυχημένης απόπειρας στο Audit Log
#         log_action(current_user.id, 'UNAUTHORIZED_ACCESS_ATTEMPT', case.id)
#         abort(403) # Access Denied
        
#     log_action(current_user.id, 'VIEW_CASE', case.id)

#     # Οι γιατροί δεν πρέπει ποτέ να λαμβάνουν στη μνήμη internal απαντήσεις που δεν τους ανήκουν
#     if current_user.role == 'admin' or current_user.id == case.user_id:
#         # Οι Admins και ο δημιουργός βλέπουν όλη την αλληλογραφία
#         replies = Reply.query.filter_by(case_id=case.id).order_by(Reply.date_created.asc()).all()
#     else:
#         # Οι υπόλοιποι γιατροί στη ροή βλέπουν ΑΠΟΚΛΕΙΣΤΙΚΑ τις επίσημες γνωμοδοτήσεις
#         replies = Reply.query.filter_by(case_id=case.id, is_internal=False).order_by(Reply.date_created.asc()).all()

#     return render_template("case_details.html", user=current_user, case=case, replies=replies)

def log_action(user_id, action, case_id=None):
    log = AuditLog(user_id=user_id, action=action, target_case_id=case_id)
    db.session.add(log)
    db.session.commit()



# @views.route('/case/<int:case_id>', methods=['GET', 'POST'])
# @login_required
# def case_details(case_id):
#     case = ClinicalCase.query.get_or_404(case_id)

#     if request.method == 'POST':
#         action_type = request.form.get('action_type')

#         # Ανοιχτό Κανάλι για τον Γιατρό ή Admin --> να στέλνει μηνύματα (Replies) στο Case
#         if action_type == 'add_internal_message':
#             if case.user_id != current_user.id:
#                 flash('You do not have permission to send messages to this case.', category='error')
#                 return redirect(url_for('views.case_details', case_id=case.id))
                
#             reply_text = request.form.get('reply_text')
#             if reply_text and len(reply_text.strip()) >= 5:
#                 new_message = Reply(
#                     reply_text=reply_text, 
#                     case_id=case.id, 
#                     user_id=current_user.id,
#                     is_internal=True
#                 )
#                 db.session.add(new_message)
#                 db.session.commit()
#                 flash('Your internal message has been added!', category='success')
#             else:
#                 flash('Your text is very small.', category='error')
#             return redirect(url_for('views.case_details', case_id=case.id))

#         # Ενέργειες αποκλειστικά για την επιτροπή των ADMINS
#         else:
#             if current_user.role != 'admin':
#                 flash('You do not have administrative privileges for this action.', category='error')
#                 return redirect(url_for('views.case_details', case_id=case.id))

#             if action_type == 'add_reply':
#                 reply_text = request.form.get('reply_text')
#                 if reply_text and len(reply_text.strip()) >= 5:
#                     new_reply = Reply(reply_text=reply_text, case_id=case.id, user_id=current_user.id, is_internal=False)
#                     db.session.add(new_reply)
#                     db.session.commit()
#                     flash('Your reply has been added!', category='success')
#                 else: 
#                     flash('Must write at least 5 characters.', category='error')
                
#             elif action_type == 'update_status':
#                 case.priority = request.form.get('status')
#                 db.session.commit()
#                 flash('Status has been updated!', category='success')
                
#             elif action_type == 'update_assignment':
#                 admin_id = request.form.get('assigned_admin_id')
#                 case.assigned_admin_id = int(admin_id) if admin_id else None
#                 db.session.commit()
#                 flash('Your assignment has been updated!', category='success')

#             return redirect(url_for('views.case_details', case_id=case.id))

#     all_admins = User.query.filter_by(role='admin').all()
#     return render_template("case_details.html", user=current_user, case=case, admins=all_admins)
