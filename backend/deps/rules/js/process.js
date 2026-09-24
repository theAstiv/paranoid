// ruleid: process-child-process-call
require('child_process').exec('ls -la');

// ruleid: process-child-process-call
require('node:child_process').spawnSync('rm', ['-rf', '/tmp/x']);

const cp1 = require('child_process');
// ruleid: process-child-process-call
cp1.exec('id');

var cp2 = require("child_process");
// ruleid: process-child-process-call
cp2.execFile('/bin/sh');

let cp3 = require('node:child_process');
// ruleid: process-child-process-call
cp3.fork('./worker.js');

// TypeScript CommonJS emit for `import { execSync } from 'child_process'`
const child_process_1 = require("child_process");
// ruleid: process-child-process-call
(0, child_process_1.execSync)('whoami');

// TypeScript emit for `import cp from 'child_process'` (esModuleInterop)
const child_process_2 = __importDefault(require("child_process"));
// ruleid: process-child-process-call
child_process_2.default.spawn('sh');

// TypeScript emit for `import * as cp from 'child_process'`
const cp4 = __importStar(require("child_process"));
// ruleid: process-child-process-call
cp4.exec('id');

const { spawn, execSync } = require('child_process');
// ruleid: process-child-process-call
execSync('whoami');

import cpDefault from 'child_process';
// ruleid: process-child-process-call
cpDefault.exec('id');

import * as cpNs from 'node:child_process';
// ruleid: process-child-process-call
cpNs.spawnSync('id');

import { execFileSync } from 'child_process';
// ruleid: process-child-process-call
execFileSync('/bin/sh');

import { exec as runCommand } from 'child_process';
// todoruleid: process-child-process-call
runCommand('id');

const notCp = require('some-other-module');
// ok: process-child-process-call
notCp.exec('ls -la');

// ok: process-child-process-call
someOtherModule.exec('ls -la');

// Passed by reference rather than called directly.
// ruleid: process-child-process-call
const execAsync1 = util.promisify(require('child_process').exec);

const cp5 = require('child_process');
// ruleid: process-child-process-call
const execAsync2 = util.promisify(cp5.exec);

const { execFile } = require('child_process');
// ruleid: process-child-process-call
const execFileAsync = util.promisify(execFile);

const cp6 = require('child_process');
// ruleid: process-child-process-call
const boundSpawn = cp6.spawn.bind(cp6);

const cp7 = require('child_process');
// ruleid: process-child-process-call
tasks.forEach(cp7.execSync);
