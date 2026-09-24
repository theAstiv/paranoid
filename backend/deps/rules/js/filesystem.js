// ruleid: filesystem-fs-write-or-delete
require('fs').writeFileSync('/etc/cron.d/evil', payload);

// ruleid: filesystem-fs-write-or-delete
require('fs/promises').rm(targetDir, { recursive: true });

// ruleid: filesystem-fs-write-or-delete
require('node:fs').promises.writeFile('/tmp/x', data);

const fs1 = require('fs');
// ruleid: filesystem-fs-write-or-delete
fs1.renameSync('/tmp/a', '/tmp/b');

var fs2 = require("fs");
// ruleid: filesystem-fs-write-or-delete
fs2.unlinkSync('/var/log/audit.log');

let fs3 = require('node:fs');
// ruleid: filesystem-fs-write-or-delete
fs3.promises.appendFile('/tmp/x', data);

// TypeScript CommonJS emit for `import { writeFileSync } from 'fs'`
const fs_1 = require("fs");
// ruleid: filesystem-fs-write-or-delete
(0, fs_1.writeFileSync)('/tmp/x', data);

// TypeScript emit for `import fs from 'fs'` (esModuleInterop)
const fs_2 = __importDefault(require("fs"));
// ruleid: filesystem-fs-write-or-delete
fs_2.default.chmodSync('/etc/shadow', 0o777);

// TypeScript emit for `import * as fs from 'fs'`
const fs_3 = __importStar(require("fs"));
// ruleid: filesystem-fs-write-or-delete
fs_3.mkdirSync('/tmp/x', { recursive: true });

const { readFileSync, unlinkSync } = require('fs');
// ruleid: filesystem-fs-write-or-delete
unlinkSync('/var/log/audit.log');

import fsDefault from 'fs';
// ruleid: filesystem-fs-write-or-delete
fsDefault.writeFileSync('/tmp/x', data);

import * as fsNs from 'node:fs';
// ruleid: filesystem-fs-write-or-delete
fsNs.rmSync('/tmp/x');

import { chmodSync } from 'node:fs';
// ruleid: filesystem-fs-write-or-delete
chmodSync('/etc/shadow', 0o777);

import { writeFile as saveFile } from 'fs/promises';
// todoruleid: filesystem-fs-write-or-delete
saveFile('/tmp/x', data);

// ok: filesystem-fs-write-or-delete
require('fs').readFileSync('/etc/passwd');

// ok: filesystem-fs-write-or-delete
fs1.existsSync('/etc/passwd');

// ok: filesystem-fs-write-or-delete
readFileSync('/etc/passwd');

const notFs = require('fs-extra-lookalike');
// ok: filesystem-fs-write-or-delete
notFs.writeFileSync('/tmp/x', data);

// Passed by reference rather than called directly.
// ruleid: filesystem-fs-write-or-delete
const writeAsync = util.promisify(require('fs').writeFile);

const fs4 = require('fs');
// ruleid: filesystem-fs-write-or-delete
paths.forEach(fs4.unlinkSync);

const { rmSync } = require('fs');
// ruleid: filesystem-fs-write-or-delete
const boundRm = rmSync.bind(null);

// ok: filesystem-fs-write-or-delete
const readAsync = util.promisify(fs4.readFile);
