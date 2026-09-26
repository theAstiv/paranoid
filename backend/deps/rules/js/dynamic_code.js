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

// Bundler-emitted CommonJS module wrapper (`require` here is the bundle's
// own local loader, shadowing the real one) — the numeric-id exclusion
// above already excludes require(4) regardless of the wrapper, with no
// separate wrapper-shape exclusion. A non-numeric require() from inside
// the same wrapper must still fire: an unconditional pattern-not-inside on
// any function whose parameters shadow `require` would itself be a bypass
// ((function (require) { require(name); })(require) smuggles the real
// require() in under a parameter literally named `require`).
function moduleWrapper(require, module, exports) {
  // ok: dynamic-code-nonliteral-require
  var x = require(4);
  // ruleid: dynamic-code-nonliteral-require
  var y = require(name);
}

// ruleid: dynamic-code-nonliteral-require
(function (require) { require(name); })(require);

// ruleid: dynamic-code-concatenated-require
require('child_' + 'process');

// Three-part concatenation: the left side ('chi' + 'ld_') is itself a
// concatenation, not a plain literal — pins that Semgrep's own constant
// folding still lets the "..." wildcard match it (a nested fold), so this
// isn't a one-step bypass of the both-literal-only pattern above.
// ruleid: dynamic-code-concatenated-require
require('chi' + 'ld_' + 'process');

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
// template string. Excluded by its exact argument shape, not by "wrapped in
// try/catch" — see the bypass case directly below for why that distinction
// matters.
var $Function = Function;
// ok: dynamic-code-aliased-function
var getEvalledConstructor = function (expressionSyntax) {
  try {
    return $Function('"use strict"; return (' + expressionSyntax + ').constructor;')();
  } catch (e) {}
};

// Regression: an earlier version of this rule excluded any aliased-Function
// call wrapped in try/catch (to match the shim above), which is itself a
// bypass — wrapping a real payload call in the same try/catch silences it.
const $F2 = Function;
try {
  // ruleid: dynamic-code-aliased-function
  $F2(payload)();
} catch (e) {}

// ruleid: dynamic-code-aliased-function
Function('return process.env')();

// ok: dynamic-code-aliased-function
Function('return this')();

// ok: dynamic-code-aliased-function
Function('return this;')();

// regenerator-runtime's global-assignment shim, bundled by nearly every
// Babel-transpiled package using async/generator functions.
// ok: dynamic-code-aliased-function
Function("r", "regeneratorRuntime = r")(runtime);

// The function-bind polyfill's arity-matching trampoline (verbatim shape,
// found live in qs's bundled dependency).
// ok: dynamic-code-aliased-function
r = Function("binder", "return function (" + joiny(i, ",") + "){ return binder.apply(this,arguments); }");

// ruleid: dynamic-code-computed-global-call
globalThis['fe' + 'tch']('http://example.com');

// ruleid: dynamic-code-computed-global-call
module['req' + 'uire']('child_process');

// Three-part concatenation: pins the same nested-fold behavior as the
// require() case above, for this rule's own pattern.
// ruleid: dynamic-code-computed-global-call
globalThis['f' + 'et' + 'ch']('http://example.com');

// ok: dynamic-code-computed-global-call
globalThis['fetch']('http://example.com');

// Ordinary browser code: toggling add/removeEventListener by a boolean.
// Constant-foldable to a string (both ternary branches are literals) but
// not a literal-plus-literal concatenation — must not fire.
// ok: dynamic-code-computed-global-call
window[(on ? 'add' : 'remove') + 'EventListener'](type, handler);

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
