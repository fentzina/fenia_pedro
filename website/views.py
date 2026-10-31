from datetime import datetime
from flask import Blueprint, render_template, request, flash, redirect, url_for, abort
from flask_login import login_required, current_user
from .models import AuditLog, ClinicalCase, Reply, User
from . import db

views = Blueprint('views', __name__)

def abort_if_not_admin():
    if current_user.role != 'admin':
        abort(403)

def log_audit_action(action_name, case_id=None):
    log = AuditLog(user_id=current_user.id, action=action_name, target_case_id=case_id)
    db.session.add(log)
    db.session.commit()

@views.route('/', methods=['GET', 'POST'])
@login_required
def home():
    if request.method == 'POST':
        #if current_user.role == 'admin':
        #    flash('Οι διαχειριστές δεν μπορούν να υποβάλουν νέα περιστατικά.', category='error')
        #    return redirect(url_for('views.home'))

        medical_condition = request.form.get('medical_condition')
        yob_input = request.form.get('yob')
        gender = request.form.get('gender')
        description = request.form.get('description')
        user_status = request.form.get('priority') 

        if user_status not in ['routine', 'urgent', 'high']:
            user_status = 'routine'

        try: 
            yob = int(yob_input) if yob_input else None
        except ValueError: 
            yob = None

        if yob is None or yob < 1900 or yob > datetime.now().year:
            flash('Enter a valid year of birth.', category='error')
        else:
            new_case = ClinicalCase(
                medical_condition=medical_condition, yob=yob, gender=gender,
                description=description, user_id=current_user.id,
                priority=user_status
            )
            
            db.session.add(new_case)
            db.session.commit()
            
            log_audit_action('CREATE_CLINICAL_CASE', new_case.id)
            flash('Your case has been submitted successfully with the selected priority!', category='success')
            return redirect(url_for('views.home'))

    approved_cases = ClinicalCase.query.filter_by(priority='accept', is_deleted=False).order_by(ClinicalCase.date_created.desc()).all()
    return render_template("home.html", user=current_user, cases=approved_cases)

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
    if current_user.role == 'admin':
        # Metrics για Case Managers (Όλα τα περιστατικά του συστήματος)
        total_triage = ClinicalCase.query.filter(ClinicalCase.priority.in_(['routine', 'urgent', 'high'])).count()
        total_board = ClinicalCase.query.filter_by(priority='board').count()
        total_resolved = ClinicalCase.query.filter_by(priority='resolved').count()
        
        # Φορτώνει όλα τα cases για τη λίστα διαχείρισης
        cases = ClinicalCase.query.order_by(ClinicalCase.date_created.desc()).all()
        return render_template("dashboard.html", user=current_user, cases=cases, triage=total_triage, board=total_board, resolved=total_resolved)
    else:
        # Metrics για απλούς Γιατρούς (Μόνο τα δικά τους περιστατικά)
        my_triage = ClinicalCase.query.filter_by(user_id=current_user.id).filter(ClinicalCase.priority.in_(['routine', 'urgent', 'high'])).count()
        my_board = ClinicalCase.query.filter_by(user_id=current_user.id, priority='board').count()
        my_resolved = ClinicalCase.query.filter_by(user_id=current_user.id, priority='resolved').count()
        
        my_cases = ClinicalCase.query.filter_by(user_id=current_user.id).order_by(ClinicalCase.date_created.desc()).all()
        return render_template("dashboard.html", user=current_user, cases=my_cases, triage=my_triage, board=my_board, resolved=my_resolved)


@views.route('/case/<int:case_id>', methods=['GET', 'POST'])
@login_required
def case_details(case_id):
    case = ClinicalCase.query.get_or_404(case_id)

    is_admin = current_user.role == 'admin'
    is_author = case.user_id == current_user.id

    # Ένας γιατρός βλέπει το case ΜΟΝΟ αν είναι ο δημιουργός του Ή αν το case έχει γίνει 'accept' (δημοσιευμένο)
    if not (is_admin or is_author or case.priority == 'accept'):
        log_audit_action('UNAUTHORIZED_ACCESS_ATTEMPT', case.id)
        abort(403)

    if request.method == 'POST':
        action_type = request.form.get('action_type')

        if action_type == 'add_internal_message':
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

        elif is_admin:
            if action_type == 'update_status':
                case.priority = request.form.get('status')
            elif action_type == 'update_assignment':
                admin_id = request.form.get('assigned_admin_id')
                case.assigned_admin_id = int(admin_id) if admin_id else None

            db.session.commit()
            flash('Updated successfully!', category='success')
            return redirect(url_for('views.case_details', case_id=case.id))

    log_audit_action('VIEW_CASE_DETAILS', case.id)

    # Admins και ο δημιουργός βλέπουν όλη την αλληλογραφία· οι υπόλοιποι ΜΟΝΟ τις επίσημες γνωμοδοτήσεις
    replies_query = Reply.query.filter_by(case_id=case.id)
    if not (is_admin or is_author):
        replies_query = replies_query.filter_by(is_internal=False)
    replies = replies_query.order_by(Reply.date_created.asc()).all()

    all_admins = User.query.filter_by(role='admin').all()

    return render_template("case_details.html", user=current_user, case=case, admins=all_admins, replies=replies)

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
    if current_user.role == 'admin':
        drafts_cases = ClinicalCase.query.filter(ClinicalCase.priority.in_(['routine', 'urgent', 'high'])).all()
        approved_cases = ClinicalCase.query.filter_by(priority='accept').all()
        rejected_cases = ClinicalCase.query.filter_by(priority='reject').all()
    else:
        drafts_cases = ClinicalCase.query.filter_by(user_id=current_user.id).filter(ClinicalCase.priority.in_(['routine', 'urgent', 'high'])).all()
        approved_cases = ClinicalCase.query.filter_by(user_id=current_user.id, priority='accept').all()
        rejected_cases = ClinicalCase.query.filter_by(user_id=current_user.id, priority='reject').all()

    return render_template(
        "archive.html", 
        user=current_user, 
        drafts=drafts_cases, 
        approved=approved_cases, 
        rejected=rejected_cases
    )


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
