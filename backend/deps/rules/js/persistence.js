// ruleid: persistence-cron-scheduler
require('node-cron').schedule('* * * * *', task);

const cron = require('node-schedule');
// ruleid: persistence-cron-scheduler
cron.schedule('0 0 * * *', task);

const { schedule } = require('node-cron');
// ruleid: persistence-cron-scheduler
schedule('* * * * *', task);

const notCron = require('some-other-lib');
// ok: persistence-cron-scheduler
notCron.schedule('* * * * *', task);

// ruleid: persistence-crontab-write
require('crontab')((err, tab) => { tab.create('node payload.js'); tab.save(); });

// ok: persistence-crontab-write
require('some-other-package')(cb);

// ruleid: persistence-shell-profile-path
const profilePath = path.join(os.homedir(), '.bashrc');

// ruleid: persistence-shell-profile-path
fs.appendFileSync("/home/user/.zshrc", payload);

// ok: persistence-shell-profile-path
const configPath = path.join(os.homedir(), '.myapprc');

// ruleid: persistence-windows-run-key
const key = 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run';

// ruleid: persistence-windows-run-key
regKey.set("HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\Updater", value);

// ok: persistence-windows-run-key
const otherKey = 'SOFTWARE\\SomeVendor\\SomeApp';
