from . import db
from flask_login import UserMixin
from sqlalchemy import event, inspect
from sqlalchemy.sql import func

# Workflow state of a case from the DOCTOR's point of view.
#   draft     -> saved but never sent; visible ONLY to its author
#   submitted -> sent to the admins/experts; enters the triage workflow
# (This is separate from `priority`, which the existing code also uses to hold
#  triage outcomes like 'accept' / 'reject' / 'resolved'.)
CASE_STATUS_DRAFT = 'draft'
CASE_STATUS_SUBMITTED = 'submitted'


class User(db.Model, UserMixin):
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(150), nullable=False)
    last_name = db.Column(db.String(150), nullable=False)
    medical_license = db.Column(db.String(100))
    role = db.Column(db.String(20), default='doctor')  # 'doctor' / 'admin'
    is_approved = db.Column(db.Boolean, default=False)
    approval_status = db.Column(db.String(20), default='pending') # 'pending', 'approved', 'rejected'
    approved_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    approved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    
    @property
    def is_active(self):
        return True
    
    # Καθαρές σχέσεις χωρίς backref που προκαλούν overlaps
    created_cases = db.relationship('ClinicalCase', backref='creator', lazy=True, foreign_keys='ClinicalCase.user_id')
    assigned_cases = db.relationship('ClinicalCase', backref='assigned_admin', lazy=True, foreign_keys='ClinicalCase.assigned_admin_id')
    replies = db.relationship('Reply', backref='admin_author', lazy=True, foreign_keys='Reply.user_id')
    audit_logs = db.relationship('AuditLog', backref='user_actor', lazy=True)

class ClinicalCase(db.Model):
    __table_args__ = (
        db.Index('idx_admin_priority', 'assigned_admin_id', 'priority'),
        db.Index('idx_owner_status', 'user_id', 'status'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # --- workflow state (NEW) -------------------------------------------------
    status = db.Column(db.String(20), nullable=False, default=CASE_STATUS_SUBMITTED,
                       server_default=CASE_STATUS_SUBMITTED)

    # --- clinical data ----------------------------------------------------------
    # Everything below is nullable at the DATABASE level on purpose: a draft is a
    # half-filled form. "Is this complete?" is enforced by the application when
    # the doctor presses Submit (see REQUIRED_FOR_SUBMISSION in views.py).
    yob = db.Column(db.Integer)                      # was a WTForms IntegerField -> never saved
    gender = db.Column(db.String(20))
    medical_condition = db.Column(db.String(255))    # required even for a draft (it is the draft's title)
    type_of_current_treatment = db.Column(db.String(255))
    descr_of_current_treatment = db.Column(db.String(255))
    dose_of_current_treatment = db.Column(db.String(255))
    date_of_current_treatment = db.Column(db.Date)

    ongoing_treatment = db.Column(db.Boolean, default=True)
    date_of_treatment_interuption = db.Column(db.Date)
    current_line_of_treatment = db.Column(db.Integer)
    karyotype_treatment = db.Column(db.String(255))
    concomitant_medication = db.Column(db.String(255))
    current_adverse_event = db.Column(db.String(255))
    previous_adverse_event = db.Column(db.Boolean, default=False, nullable=False)
    comorbidities = db.Column(db.String(255))

    grade_of_current_adverse_event = db.Column(db.Integer)
    cycle_of_current_adverse_event = db.Column(db.Integer)
    days_since_current_adverse_event = db.Column(db.Integer)

    ighv = db.Column(db.String(20), default='Unknown')
    del17p = db.Column(db.String(50), default='Unknown')
    tp53 = db.Column(db.String(50), default='Unknown')

    description = db.Column(db.Text)
    
    date_created = db.Column(db.DateTime(timezone=True), default=func.now())
    updated_at = db.Column(db.DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    priority = db.Column(db.String(20), default='routine')
    assigned_admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_deleted = db.Column(db.Boolean, default=False)
    hidden_by_author = db.Column(db.Boolean, default=False, nullable=False)
    
    admin_retention_status = db.Column(db.String(20), default='active') # 'active', 'archived', 'purged' 

    replies = db.relationship('Reply', backref='clinical_case', lazy=True, cascade="all, delete-orphan")

class Reply(db.Model):
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    reply_text = db.Column(db.Text, nullable=False)
    date_created = db.Column(db.DateTime(timezone=True), default=func.now())
    case_id = db.Column(db.Integer, db.ForeignKey('clinical_case.id', ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_internal = db.Column(db.Boolean, default=False, nullable=False)
    
    author = db.relationship('User', foreign_keys=[user_id], overlaps="admin_author,replies", lazy=True)

class AuditLog(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(100), nullable=False) # e.g., 'VIEW_CASE', 'UPDATE_TRIAGE'
    target_case_id = db.Column(db.Integer, nullable=True)
    timestamp = db.Column(db.DateTime(timezone=True), default=func.now())
    


# ---------------------------------------------------------------------------
# Data-layer lock: the three baseline biomarkers cannot change once a case has
# been SUBMITTED. This sits under the views on purpose: even a future route, a
# script or a typo cannot silently rewrite what the author reported.
# (A draft stays fully editable, and the draft -> submitted flush is allowed
#  because the status BEFORE that flush is still 'draft'.)
# ---------------------------------------------------------------------------
LOCKED_AFTER_SUBMISSION = ('ighv', 'del17p', 'tp53')


@event.listens_for(ClinicalCase, 'before_update')
def _lock_biomarkers_after_submission(mapper, connection, case):
    state = inspect(case)
    status_history = state.attrs.status.history
    status_before = status_history.deleted[0] if status_history.deleted else case.status
    if status_before != CASE_STATUS_SUBMITTED:
        return
    for field in LOCKED_AFTER_SUBMISSION:
        if state.attrs[field].history.has_changes():
            raise ValueError(f"'{field}' is locked: this case has already been submitted.")
