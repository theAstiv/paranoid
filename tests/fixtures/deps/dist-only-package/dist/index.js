const https = require('https');
https.request({ host: 'example.invalid' });

const { execSync } = require('child_process');
execSync('echo hi');
