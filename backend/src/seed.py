from sqlalchemy import select
from .database import Session
from .models import *
from .auth import password_hash
from .constants import Role
from .conflict_service import normalize
from .algorithm import classify

def seed():
    with Session() as db:
        for role in Role:
            if not db.scalar(select(User).where(User.username==role.value)):db.add(User(username=role.value,password=password_hash('Aid@2026'),role=role.value))
        for topic,title in [('labor','劳动报酬记录'),('housing','脱敏租赁合同'),('consumer','脱敏购物凭证')]:
            for code,name in [('identity','脱敏身份授权页'),('evidence',title)]:
                if not db.scalar(select(Requirement).where(Requirement.topic==topic,Requirement.code==code)):db.add(Requirement(topic=topic,code=code,title=name))
        for code,name,capacity,specialties in [('YN','友邻服务站',2,'labor,housing'),('HM','和睦接待室',3,'labor,consumer'),('AH','安居协作点',2,'housing,consumer')]:
            if not db.scalar(select(Agency).where(Agency.code==code)):db.add(Agency(code=code,name=name,capacity=capacity,specialties=specialties,active_count=0))
        db.flush()
        records=[('LZ030','青桥授权代表','单位劳动合同 工资考勤 劳动报酬 登记分流','青桥商行','模拟前合作人',True,''),('LZ031','来访者林某','青桥商行拖欠工资，加班工时尚未结算，需劳动报酬行政分流','模拟林某','青桥商行',True,''),('LZ032','未授权来访者','房东不退租房押金，房屋租赁合同仍在补齐','模拟陈某','模拟房东',False,''),('LZ033','主题待核访客','最近发生一些事情，希望有人帮助记录和联系相关接待人员','模拟周某','模拟相对人',True,''),('LZ034','欠薪来访者吴某','用工单位拖欠工资和加班报酬，希望追讨劳动报酬','模拟吴某','模拟用工单位',True,'来访自带一叠租金收据和房屋租赁合同，称与房东就退租押金和房屋维修发生争执，要求处理住房租赁问题')]
        for code,alias,facts,client,opponent,authorized,summary in records:
            if db.scalar(select(Intake).where(Intake.code==code)):continue
            case=Intake(code=code,alias=alias,facts=facts,materials_summary=summary,materials_version=1 if summary else 0,status='accepted' if code=='LZ030' else 'open');db.add(case);db.flush();db.add(Consent(intake_id=case.id,authorized=authorized,basis='模拟授权签名存根' if authorized else '未签署授权'))
            for side,name in [('client',client),('opponent',opponent)]:
                party=db.scalar(select(Party).where(Party.normalized==normalize(name)))
                if not party:party=Party(name=name,normalized=normalize(name));db.add(party);db.flush()
                db.add(CaseParty(intake_id=case.id,party_id=party.id,side=side))
            label,confidence,metrics=classify(facts)
            materials_label=materials_confidence=None
            if summary:
                materials_label,materials_confidence,_=classify(summary)
            conflict=bool(summary) and materials_label!=label
            reviewed=code not in ('LZ033','LZ034')
            approved=None
            if reviewed:approved='labor' if code in ('LZ030','LZ031') else 'housing'
            triage=Triage(intake_id=case.id,facts_version=1,materials_version=case.materials_version,status='reviewed' if reviewed else 'done',predicted=label,confidence=confidence,materials_predicted=materials_label,materials_confidence=materials_confidence,source_conflict=conflict,adopted_source=('facts' if not conflict else None) if reviewed else None,approved=approved,manual_required=confidence<.68 or conflict,review_note='接待主管核对主题' if reviewed else '',metrics=metrics);db.add(triage)
            if code=='LZ030':
                agency=db.scalar(select(Agency).where(Agency.code=='YN'));agency.active_count+=1
                db.add(Referral(intake_id=case.id,agency_id=agency.id,topic='labor',status='accepted',receipt='YN-ACK-030',note='模拟相对方关联承接，用于冲突核验'))
                for req in db.scalars(select(Requirement).where(Requirement.topic=='labor')):db.add(Document(intake_id=case.id,requirement_id=req.id,reference='LZ030-脱敏档案.pdf',status='verified',note='已核验'))
            elif code=='LZ031':
                req=db.scalar(select(Requirement).where(Requirement.topic=='labor',Requirement.code=='identity'));db.add(Document(intake_id=case.id,requirement_id=req.id,reference='LZ031-脱敏身份.pdf',status='verified',note='缺工资材料，待补正'))
        db.commit()
if __name__=='__main__':seed()
