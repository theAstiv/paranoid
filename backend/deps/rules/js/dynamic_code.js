// ruleid: dynamic-code-new-function
const f = new Function('return process.env');

// ok: dynamic-code-new-function
const f2 = new SafeFunction('return 1');

// ruleid: dynamic-code-eval
eval(userInput);

// ok: dynamic-code-eval
myEvalLikeHelper(userInput);

// ruleid: dynamic-code-vm-module
require('vm').runInNewContext(code);

// ruleid: dynamic-code-vm-module
require('node:vm').runInThisContext(code);

const vm1 = require('vm');
// ruleid: dynamic-code-vm-module
vm1.runInNewContext(code);

var vm2 = require("vm");
// ruleid: dynamic-code-vm-module
new vm2.Script(code);

// TypeScript CommonJS emit for `import { runInThisContext } from 'vm'`
const vm_1 = require("vm");
// ruleid: dynamic-code-vm-module
(0, vm_1.runInThisContext)(code);

// TypeScript emit for `import vm from 'vm'` (esModuleInterop)
const vm_2 = __importDefault(require("vm"));
// ruleid: dynamic-code-vm-module
vm_2.default.compileFunction(code);

const { Script, runInThisContext } = require('vm');
// ruleid: dynamic-code-vm-module
runInThisContext(code);

// ruleid: dynamic-code-vm-module
new Script(code);

import vmDefault from 'vm';
// ruleid: dynamic-code-vm-module
vmDefault.runInNewContext(code);

import * as vmNs from 'node:vm';
// ruleid: dynamic-code-vm-module
vmNs.runInThisContext(code);

import { compileFunction } from 'vm';
// ruleid: dynamic-code-vm-module
compileFunction(code);

// ok: dynamic-code-vm-module
require('some-vm-lib').runInNewContext(code);

// Passed by reference rather than called directly.
const vm3 = require('vm');
// ruleid: dynamic-code-vm-module
snippets.forEach(vm3.runInThisContext);

const { runInNewContext } = require('vm');
// ruleid: dynamic-code-vm-module
const boundRun = runInNewContext.bind(null);
