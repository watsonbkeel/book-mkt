"""Current release verification wrapper: synthetic schema3 migration and isolated UI.
No baseline ZIP or private history import. No production Worker/services are started.
"""
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--skip-browser',action='store_true')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    command=[sys.executable,'-m','pytest','-q','tests/test_upgrade_contract.py::test_actual_schema3_ddl_migration_backup_and_rollback','tests/test_v11_upgrade_script.py','tests/test_operations.py']
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
    (args.output/'migration-tests.txt').write_text(result.stdout+result.stderr)
    if result.returncode:raise SystemExit(result.returncode)
    report={'migration_tests_exit':0,'private_history_imported':False,'production_access':False}
    if not args.skip_browser:
        from check_upgrade_ui import run
        report['browser']=run(args.output/'ui')
    (args.output/'verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
if __name__=='__main__':main()
