"""Hourly server job: refresh, validate, commit only public feeds, push and mirror."""
from pathlib import Path
import fcntl
import shutil
import subprocess
from common import ROOT, STATE, now
from sync_data import run
from validate_data import validate

GENERATED={'honors_data.json','schedule_data.json','research_data.json','applications.json','admissions_updates.json'}
COMMIT_PREFIX='Update public course, admissions and research feeds '

def git(*args,check=True):
    return subprocess.run(['git',*args],cwd=ROOT,check=check,text=True,capture_output=True,timeout=120)

def generated(path):
    return path in GENERATED or path.startswith('assets/honors/')

def assert_publisher_commits():
    for commit in git('rev-list','origin/main..HEAD').stdout.splitlines():
        if not git('show','-s','--format=%s',commit).stdout.startswith(COMMIT_PREFIX):
            raise RuntimeError('Unpublished manual commit found; leaving it for its author')
        paths=git('diff-tree','--no-commit-id','--name-only','-r','-z',commit).stdout.split('\0')
        if any(p and not generated(p) for p in paths):
            raise RuntimeError('Pending commit contains source changes; not publishing automatically')

def integrate_remote():
    git('fetch','origin','main')
    assert_publisher_commits()
    result=git('merge','--ff-only','origin/main',check=False)
    if result.returncode:
        # Reapply only validated, unpublished feed commits. Never force-push.
        result=git('rebase','--autostash','origin/main',check=False)
        if result.returncode:
            git('rebase','--abort',check=False)
            raise RuntimeError('Remote update conflicts with pending feeds; previous work retained')

def mirror(commit=None):
    commit=commit or git('rev-parse','HEAD').stdout.strip()
    target=ROOT.parent/'网页文件'
    public=('index.html','assets/','images/','封面图片/')
    paths=git('ls-tree','-r','--name-only','-z',commit).stdout.split('\0')
    for name in paths:
        if not name or not (name in GENERATED or any(name==p or name.startswith(p) for p in public)):
            continue
        destination=target/name
        if destination.is_symlink() or any(parent.is_symlink() for parent in destination.parents):
            raise RuntimeError('Refusing to mirror through a symbolic link: '+name)
        content=subprocess.run(['git','show',commit+':'+name],cwd=ROOT,check=True,capture_output=True,timeout=30).stdout
        if destination.exists() and content==destination.read_bytes():
            continue
        destination.parent.mkdir(parents=True,exist_ok=True)
        temporary=destination.with_suffix(destination.suffix+'.sync-tmp')
        if temporary.is_symlink():
            raise RuntimeError('Unexpected mirror temporary symlink')
        temporary.write_bytes(content)
        temporary.replace(destination)

def main():
    STATE.mkdir(exist_ok=True)
    with (STATE/'publisher.lock').open('w') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('An update is already running; skipped.')
            return 0
        if git('branch','--show-current').stdout.strip()!='main':
            raise RuntimeError('Publisher requires main branch')
        changed=git('diff','--name-only','-z').stdout.split('\0')+git('diff','--cached','--name-only','-z').stdout.split('\0')+git('ls-files','--others','--exclude-standard','-z').stdout.split('\0')
        if any(p and not generated(p) for p in changed):
            raise RuntimeError('Source edits are present; automated publish paused for this run')
        integrate_remote()
        results=run()
        print('Validated:',validate(),flush=True)
        git('add','--',*sorted(GENERATED),'assets/honors')
        if git('diff','--cached','--quiet',check=False).returncode:
            git('commit','-m',COMMIT_PREFIX+now()[:10])
        pushed=git('push','origin','main',check=False)
        if pushed.returncode:
            integrate_remote()
            validate()
            git('push','origin','main')
        commit=git('rev-parse','HEAD').stdout.strip()
        mirror(commit)
        print('Published and mirrored',commit,flush=True)
        return 0 if all(r['ok'] for r in results.values()) else 1

if __name__=='__main__':
    raise SystemExit(main())
