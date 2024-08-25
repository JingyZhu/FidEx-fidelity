## Doc still under working

# FidEx record and replay, and fidelity checking code

## Prerequisites
To setup the environment, mainly need to prepare for the following:
- Python packages:
```bash
pip install -r requirements.txt
```

- Node packages:
```bash
npm install
```

- pywb and webrecorder:
    - pywb:
        - Download and install pywb from [here](https://github.com/webrecorder/pywb)
    - webrecorder:
        - The `npm install` will install puppeteer, which will download a Chrome test binary. To enable the record of webpages, need to install the webrecorder extension from [here](https://chromewebstore.google.com/detail/webrecorder-archivewebpag/fpeoodllldobpkbkabpblcfaogecpndd?pli=1)

## Record and replay
The record and replay code is mainly in the `record_replay` folder. The code is mainly for running record and replay on the browser with webrecorder and pywb. The code is mainly for the following workflow:
### Shared flags:
```bash
cd record_replay && node record.js --help
```

```bash
Usage: record [options] <url>

Options:
  -d --dir <directory>             Directory to save page info (default: "pageinfo/test")
  --download <downloadPath>        Directory to save downloads (default: "downloads")
  -f --file <filename>             Filename prefix (default: "dimension")
  -a --archive <Archive>           Archive list to record the page (default: "test")
  -m, --manual                     Manual control for finishing loading the page
  -i, --interaction                Interact with the page
  -w, --write                      Collect writes to the DOM
  -s, --screenshot                 Collect screenshot and other measurements
  --remove                         Remove recordings after finishing loading the page
  --scroll                         Scroll to the bottom.
  -c, --chrome_data <chrome_data>  Directory of Chrome data
  --headless                       If run in headless mode
  -p --proxy <proxy>               Proxy server to use. Note that is chrome is installed with extensions that controls
                                   proxy, this could not work.
  -e --exetrace                    Enable execution trace for both js run and network fetches
  -h, --help                       display help for command
```
- Record the page with webrecorder (```record.js```)
    ```bash
    node record.js [flags] <url>
    ```
    The record.js will automatically download the warc file after the page is loaded.

- Upload the warc file to pywb
    ```bash
    wb-manager add <col> <recorded_warc_file>
    ```

- Replay the page with pywb (```replay.js```)
    ```bash
    node replay.js [flags] <url>
    ```


## Fidelity check