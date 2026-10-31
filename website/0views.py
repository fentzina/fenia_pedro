import os
from flask import Blueprint, render_template, request, flash, redirect, url_for, abort
from flask_login import login_required, current_user
from .models import User, ClinicalCase, Reply
from . import db

views = Blueprint('views', __name__)

@views.route('/', methods=['GET', 'POST'])
@login_required
def home():
    if request.method == 'POST':
        # if current_user.role == 'admin':
        #     flash('Οι διαχειριστές δεν μπορούν να υποβάλουν νέα περιστατικά.', category='error')
        #     return redirect(url_for('views.home'))

        medical_condition = request.form.get('medical_condition')
        age_input = request.form.get('age')
        gender = request.form.get('gender')
        description = request.form.get('description')
        user_status = request.form.get('priority') 

        if user_status not in ['routine', 'urgent', 'high']:
            user_status = 'routine'

        try: 
            age = int(age_input) if age_input else None
        except ValueError: 
            age = None

        if age is None or age < 0 or age > 120:
            flash('Please enter a valid age.', category='error')
        else:
            new_case = ClinicalCase(
                medical_condition=medical_condition, age=age, gender=gender,
                description=description, user_id=current_user.id,
                priority=user_status
            )
            db.session.add(new_case)
            db.session.commit()
            flash('The clinical case has been submitted successfully!', category='success')
            return redirect(url_for('views.home'))

    approved_cases = ClinicalCase.query.filter_by(priority='accept').order_by(ClinicalCase.date_created.desc()).all()
    return render_template("home.html", user=current_user, cases=approved_cases)


@views.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        total_triage = ClinicalCase.query.filter(ClinicalCase.priority.in_(['routine', 'urgent', 'high'])).count()
        total_accepted = ClinicalCase.query.filter_by(priority='accept').count()
        total_rejected = ClinicalCase.query.filter_by(priority='reject').count()
        cases = ClinicalCase.query.order_by(ClinicalCase.date_created.desc()).all()
    else:
        total_triage = ClinicalCase.query.filter_by(user_id=current_user.id).filter(ClinicalCase.priority.in_(['routine', 'urgent', 'high'])).count()
        total_accepted = ClinicalCase.query.filter_by(user_id=current_user.id, priority='accept').count()
        total_rejected = ClinicalCase.query.filter_by(user_id=current_user.id, priority='reject').count()
        cases = ClinicalCase.query.filter_by(user_id=current_user.id).order_by(ClinicalCase.date_created.desc()).all()
        
    return render_template("dashboard.html", user=current_user, cases=cases, 
                           triage=total_triage, board=total_accepted, resolved=total_rejected)


@views.route('/archive')
@login_required
def archive():
    if current_user.role == 'admin':
        drafts_cases = ClinicalCase.query.filter(ClinicalCase.priority.in_(['routine', 'urgent', 'high'])).all()
        accepted_cases = ClinicalCase.query.filter_by(priority='accept').all()
        rejected_cases = ClinicalCase.query.filter_by(priority='reject').all()
    else:
        drafts_cases = ClinicalCase.query.filter_by(user_id=current_user.id).filter(ClinicalCase.priority.in_(['routine', 'urgent', 'high'])).all()
        accepted_cases = ClinicalCase.query.filter_by(user_id=current_user.id, priority='accept').all()
        rejected_cases = ClinicalCase.query.filter_by(user_id=current_user.id, priority='reject').all()

    return render_template("archive.html", user=current_user, drafts=drafts_cases, approved=accepted_cases, rejected=rejected_cases)


@views.route('/case/<int:case_id>', methods=['GET', 'POST'])
@login_required
def case_details(case_id):
    case = db.session.get(ClinicalCase, case_id)
    if not case:
        abort(404)

    if request.method == 'POST':
        action_type = request.form.get('action_type')

        if action_type == 'add_internal_message':
            reply_text = request.form.get('reply_text')
            if reply_text and len(reply_text.strip()) >= 5:
                new_message = Reply(reply_text=reply_text, case_id=case.id, user_id=current_user.id, is_internal=True)
                db.session.add(new_message)
                db.session.commit()
                flash('The internal comment has been added!', category='success')
            return redirect(url_for('views.case_details', case_id=case.id))

        elif action_type == 'triage_action':
            if current_user.role != 'admin':
                abort(403)
                
            new_status = request.form.get('status')
            raw_admin_id = request.form.get('assigned_admin_id')
            
            if new_status in ['routine', 'urgent', 'high', 'accept', 'reject']:
                case.priority = new_status

            if raw_admin_id and raw_admin_id.strip() != "" and raw_admin_id.strip() != "None":
                try:
                    case.assigned_admin_id = int(raw_admin_id.strip())
                except ValueError:
                    case.assigned_admin_id = None
            else:
                case.assigned_admin_id = None

            db.session.add(case)
            db.session.commit()
            db.session.refresh(case)
            
            flash('Updated!', category='success')
            return redirect(url_for('views.case_details', case_id=case.id))

    all_admins = User.query.filter_by(role='admin').all()
    replies = Reply.query.filter_by(case_id=case.id).all()
    return render_template("case_details.html", user=current_user, case=case, admins=all_admins, replies=replies)


@views.route('/user-management', methods=['GET', 'POST'])
@login_required
def user_management():
    if current_user.role != 'admin':
        abort(403)
        
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        action = request.form.get('action')
        target_user = db.session.get(User, int(user_id)) if user_id else None
        
        if target_user:
            if action == 'approve':
                target_user.approval_status = 'approved'
                flash(f'The user {target_user.first_name} has been approved!', category='success')
            elif action == 'reject':
                target_user.approval_status = 'rejected'
                flash(f'The user {target_user.first_name} has been rejected.', category='error')
            elif action == 'change_role':
                new_role = request.form.get('new_role')
                if new_role in ['doctor', 'admin']:
                    target_user.role = new_role
                    flash(f'The role has been changed to {new_role}!', category='success')
            db.session.commit()
            return redirect(url_for('views.user_management'))

    pending_users = User.query.filter_by(approval_status='pending', role='doctor').all()
    active_members = User.query.filter((User.id != current_user.id) & ((User.approval_status == 'approved') | (User.role == 'admin'))).all()
    return render_template("user_management.html", user=current_user, pending_users=pending_users, all_users=active_members)
