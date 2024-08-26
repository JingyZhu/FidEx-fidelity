import sys
import os
from subprocess import call

_cur_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(_cur_dir))
import fidelity_detect
sys.path.append(os.path.dirname(os.path.dirname(_cur_dir)))
from utils import url_utils
from record_replay import autorecord

TESTDIR = 'test_data'
# TODO: Need to change to where the pywb is running on and the archive is stored
ARCHIVEDIR = os.path.join(os.path.expanduser("~"), 'fidelity-files')
PYWBVENV = '/x/jingyz/pywb/env/bin/activate'


def test_no_issue_record_replay_gt():
    # ! Clean and setup webrecorder's test archive before running
    call(f'rm -rf {ARCHIVEDIR}/writes/test/*_rr', shell=True)
    call(f'rm -rf {TESTDIR}/*_rr', shell=True)
    call(f'rm -rf {ARCHIVEDIR}/collections/test/', shell=True)
    call(f'source {PYWBVENV} && wb-manager init test', shell=True, executable="/bin/bash", cwd=f'{ARCHIVEDIR}')
    urls = [
        "https://www.google.com/",
        # Some manually checked testcases from Tranco. No guarantee of future correctness
        # "https://bookhodai.jp/",
        # "https://www.dearfoams.com/", # * Issue caused by fail to clear storage (popup only on first visit)
        # "https://crpt.ru/", # * Image carousel
        # "https://mojohost.com/", # * Recaptcha
    ]
    dir_issue = {}
    for i, url in enumerate(urls):
        print(i, url)
        archive_name = url_utils.calc_hostname(url)
        archive_name = f'{archive_name}_rr'
        _, url = autorecord.record_replay(url, archive_name,
                                          write_path=f'{_cur_dir}/{TESTDIR}', 
                                          download_path=f'{_cur_dir}/downloads', 
                                          archive_path=ARCHIVEDIR,
                                          wr_archive='test', pw_archive='test', remote_host=False)
        dirr = archive_name
        call(f'cp -r {ARCHIVEDIR}/writes/test/{dirr} {TESTDIR}/{dirr}', shell=True)
        full_dir = os.path.join(TESTDIR, dirr)
        issue, (left_u, right_u) = fidelity_detect.fidelity_issue(full_dir, 'live', 'archive', meaningful=True)
        dir_issue[dirr] = issue
    print("\n\n==========Test Results==========")
    for dirr, issue in dir_issue.items():
        print(dirr, "has issue", issue)


if __name__ == "__main__":
    test_no_issue_record_replay_gt()
