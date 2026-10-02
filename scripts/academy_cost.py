"""Conditional public-price scenario, not an account quote or a spend cap."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path


def estimate():
    # Public AWS references consulted 2026-10-02; no account-specific discount verified.
    rates=dict(t3_medium_hour=.0418,t3a_medium_hour=.0376,gp3_gb_month=.08,
               ipv4_hour=.005,internet_gb=.09,snapshot_gb_month=.05,interzone_gb_each_end=.01)
    rows=[]
    for hours in (2,4,8):
        r=dict(hours=hours,instance_hours=3*hours,compute=3*hours*rates['t3_medium_hour'],
            ebs=84*rates['gp3_gb_month']*hours/720,ipv4=3*hours*rates['ipv4_hour'],
            internet_allowance_gb=10,internet=.9,paid_snapshots=0,extra_components=0)
        r['total_usd']=sum(r[k] for k in ('compute','ebs','ipv4','internet','paid_snapshots','extra_components'))
        r['t3a_total_if_permitted']=r['total_usd']-3*hours*(rates['t3_medium_hour']-rates['t3a_medium_hour'])
        rows.append(r)
    return dict(status='ESTIMACION_CONDICIONAL_NO_AUTORIZADA',date='2026-10-02',reference_region='us-east-1',
        actual_region=None,reported_general_credit_usd=50,verified_balance=None,free_benefits_verified=[],rates=rates,
        sessions=rows,stopped=[dict(days=d,ebs_usd=84*.08*d/30,auto_public_ip_usd=0,
            optional_3gib_snapshot_usd=3*.05*d/30,elastic_ip_if_retained_usd=3*.005*24*d) for d in (7,30)],
        optional_fourth_vm_2h=dict(compute=2*.0418,ipv4=2*.005,ebs=28*.08*2/720,
            retained_7days=28*.08*7/30),multi_zone_example=dict(ss_gb=10,extra_usd=10*.01*2),
        assumptions=['3 independent VMs; 16 GiB root + 12 GiB data each; 30-day/720h cost divisor',
            'Conservative 10 GB total Internet egress including encrypted local backup; no free allowance deduction',
            'No paid snapshots by default; local encrypted backup on existing external disk',
            'Regional EBS/traffic quotes, Academy restrictions, taxes and account eligibility still need verification',
            'No fourth VM authorized; no automatic deletion; residual storage accrues until explicitly retired'],
        sources=['https://aws.amazon.com/ec2/instance-types/t3/','https://aws.amazon.com/ebs/pricing/',
                 'https://aws.amazon.com/ebs/volume-types/','https://aws.amazon.com/vpc/pricing/',
                 'https://aws.amazon.com/ec2/pricing/on-demand/'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(estimate(),indent=2)+'\n',encoding='utf-8')
    print(str(a.output))
