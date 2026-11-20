from sqlalchemy import select
from .models import Intake,Consent,Agency,now
from .common import get,reject,finish,active_referral,editable

def create(db,data,user):
    reject(db.scalar(select(Intake).where(Intake.code==data.code)) is not None,'收件编号已存在')
    payload=data.model_dump();payload['materials_summary']=payload['materials_summary'].strip()
    if payload['materials_summary']:payload['materials_version']=1
    row=Intake(**payload);db.add(row);db.flush();db.add(Consent(intake_id=row.id,authorized=False,basis='尚未取得转介授权'));return finish(db,user,'来访建卷',row)
def revise(db,id,data,user):
    row=editable(db,id);row.facts=data.facts;row.facts_version+=1;return finish(db,user,'事实更正并更新版本',row)
def revise_materials(db,id,data,user):
    row=editable(db,id);summary=data.materials_summary.strip()
    if summary!=(row.materials_summary or ''):
        row.materials_summary=summary;row.materials_version=(row.materials_version or 0)+1
        return finish(db,user,'登记自带材料摘要并更新版本',row)
    return finish(db,user,'自带材料摘要未变化',row)
def consent(db,id,data,user):
    case=get(db,Intake,id,True);row=db.scalar(select(Consent).where(Consent.intake_id==id))
    reject(case.status=='closed','销案卷宗只读')
    ref=active_referral(db,id)
    if not data.authorized and ref is not None:
        agency=get(db,Agency,ref.agency_id,True);agency.active_count-=1;ref.status='withdrawn';ref.note='来访人撤回授权，自动退回';case.status='open'
    row.authorized=data.authorized;row.basis=data.basis;row.at=now();return finish(db,user,'授权更新',row)
def authorized(db,id):
    row=db.scalar(select(Consent).where(Consent.intake_id==id))
    return row is not None and row.authorized
