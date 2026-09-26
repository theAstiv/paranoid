// ruleid: native-ffi-node-addon-require
require('./build/Release/addon.node');

// ruleid: native-ffi-node-addon-require
require("../prebuilds/linux-x64/addon.node");

// ok: native-ffi-node-addon-require
require('./index.js');

// ruleid: native-ffi-bindings-module
require('bindings')('addon');

// ruleid: native-ffi-bindings-module
require("node-gyp-build")(__dirname);

// ok: native-ffi-bindings-module
require('some-other-loader')('addon');

// ruleid: native-ffi-ffi-napi-library
new (require('ffi-napi')).Library('libm', { ceil: ['double', ['double']] });

const ffi = require('ffi-napi');
// ruleid: native-ffi-ffi-napi-library
new ffi.Library('libc', { system: ['int', ['string']] });

const { Library } = require('ffi-napi');
// ruleid: native-ffi-ffi-napi-library
new Library('libc', { system: ['int', ['string']] });

const notFfi = require('some-other-lib');
// ok: native-ffi-ffi-napi-library
new notFfi.Library('libc', {});

// ruleid: native-ffi-process-binding
process.binding('fs');

// ruleid: native-ffi-process-binding
process._linkedBinding('fs');

// ruleid: native-ffi-process-binding
process.dlopen(module, './addon.node');

// ok: native-ffi-process-binding
myProcess.binding('fs');
