## Still under working

# FidEx record and replay, and fidelity checking code
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