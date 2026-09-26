// ruleid: dynamic-code-new-function
const f = new Function('return process.env');

// ok: dynamic-code-new-function
const f2 = new SafeFunction('return 1');

// ruleid: dynamic-code-eval
eval(userInput);

// ok: dynamic-code-eval
myEvalLikeHelper(userInput);

// ruleid: dynamic-code-nonliteral-require
require(moduleNameFromEnv);

// ruleid: dynamic-code-nonliteral-require
require(`./plugins/${pluginName}`);

// ok: dynamic-code-nonliteral-require
require('lodash');

// ok: dynamic-code-nonliteral-require
require("./local-helper");

// Browserify/webpack bundle shape: numeric module ids are never real
// Node require() calls.
// ok: dynamic-code-nonliteral-require
require(4);
// ok: dynamic-code-nonliteral-require
require(46);

// Bundler-emitted CommonJS module wrapper: `require` here is the bundle's
// own local loader, shadowing the real one.
function moduleWrapper(require, module, exports) {
  // ok: dynamic-code-nonliteral-require
  var x = require(4);
}

// ruleid: dynamic-code-concatenated-require
require('child_' + 'process');

// ok: dynamic-code-concatenated-require
require('lodash');

const aliasedRequire = require;
// ruleid: dynamic-code-aliased-require
aliasedRequire('child_process');

// ruleid: dynamic-code-aliased-require
(0, require)('child_process');

// ok: dynamic-code-aliased-require
require('lodash');

const aliasedFn = Function;
// ruleid: dynamic-code-aliased-function
aliasedFn('return process.env')();

// ruleid: dynamic-code-aliased-function
(0, Function)('return process.env')();

// ruleid: dynamic-code-aliased-function
(function(){}).constructor('return process.env')();

// Real-world benign shim (get-intrinsic/es-abstract/has-property-descriptors
// et al.): feature-detects a working `Function` constructor with a fixed
// template string, guarded by try/catch — not attacker-influenced code.
var $Function = Function;
// ok: dynamic-code-aliased-function
var getEvalledConstructor = function (expressionSyntax) {
  try {
    return $Function('"use strict"; return (' + expressionSyntax + ').constructor;')();
  } catch (e) {}
};

// ruleid: dynamic-code-computed-global-call
globalThis['fe' + 'tch']('http://example.com');

// ruleid: dynamic-code-computed-global-call
module['req' + 'uire']('child_process');

// ok: dynamic-code-computed-global-call
globalThis['fetch']('http://example.com');

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
