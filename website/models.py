from datetime import datetime
import wtforms
import flask_wtf

from wtforms import IntegerField
from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, SubmitField
from wtforms.validators import DataRequired, NumberRange
from . import db
from flask_login import UserMixin
from sqlalchemy.sql import func


current_year = datetime.now().year

class User(db.Model, UserMixin):
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(150), nullable=False)
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
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    yob = IntegerField('Έτος Γέννησης', validators=[
        DataRequired(), 
        NumberRange(min=1900, max=current_year, message="Παρακαλώ εισάγετε ένα έγκυρο έτος γέννησης.")
    ])
    gender = db.Column(db.String(20), nullable=False)
    medical_condition = db.Column(db.String(255), nullable=False)
    type_of_current_treatment = db.Column(db.String(255), nullable=False)
    descr_of_current_treatment = db.Column(db.String(255), nullable=True)
    dose_of_current_treatment = db.Column(db.String(255), nullable=False)
    date_of_current_treatment = db.Column(db.Integer, nullable=False)
    
    ongoing_treatment = db.Column(db.Boolean, nullable=True) 
    date_of_treatment_interuption = db.Column(db.Integer, nullable=False)
    current_line_of_treatment = db.Column(db.String(255), nullable=False)
    karyotype_treatment = db.Column(db.String(255), nullable=True)
    concomitant_medication = db.Column(db.String(255), nullable=False, default="None")
    current_adverse_event = db.Column(db.Integer, nullable=False)
    previous_adverse_event = db.Column(db.Boolean, default=False, nullable=False)
    comorbidities = db.Column(db.String(255), nullable=False, default="None")
    
    grade_of_current_adverse_event = db.Column(db.Integer, nullable=False)
    cycle_of_current_adverse_event = db.Column(db.Integer, nullable=False)
    days_since_current_adverse_event = db.Column(db.Integer, nullable=False)
    
    ighv = db.Column(db.String(20), default='Unmutated') # 'Unmutated', 'mutated'
    del17p = db.Column(db.String(50), default="Not assessed") # "Not assessed", "Traditional/Standard Cut-offs", "Optimal/High-Risk Thresholds", "Double-Hit / Biallelic Inactivation"
    tp53 = db.Column(db.String(50), default="Not assessed")   # "Wild-type", "Mutated", "VAF", "Not assessed"
    
    description = db.Column(db.Text, nullable=False)
    
    date_created = db.Column(db.DateTime(timezone=True), default=func.now())
    updated_at = db.Column(db.DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    priority = db.Column(db.String(20), default='routine')
    assigned_admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_deleted = db.Column(db.Boolean, default=False)
    hidden_by_author = db.Column(db.Boolean, default=False, nullable=False)
    
    __table_args__ = (
        db.Index('idx_admin_priority', 'assigned_admin_id', 'priority'),
        #{'extend_existing': True}
    )
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
    