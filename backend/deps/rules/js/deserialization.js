// ruleid: deserialization-node-serialize-unserialize
require('node-serialize').unserialize(payload);

const ns = require('node-serialize');
// ruleid: deserialization-node-serialize-unserialize
ns.unserialize(payload);

const { unserialize } = require('node-serialize');
// ruleid: deserialization-node-serialize-unserialize
unserialize(payload);

const notNodeSerialize = require('some-other-lib');
// ok: deserialization-node-serialize-unserialize
notNodeSerialize.unserialize(payload);

// ruleid: deserialization-js-yaml-unsafe-load
require('js-yaml').load(untrustedYaml);

const yaml = require('js-yaml');
// ruleid: deserialization-js-yaml-unsafe-load
yaml.load(untrustedYaml);

const { load } = require('js-yaml');
// ruleid: deserialization-js-yaml-unsafe-load
load(untrustedYaml);

// ok: deserialization-js-yaml-unsafe-load
yaml.safeLoad(untrustedYaml);

// ruleid: deserialization-unserialize-package-call
require('unserialize')(payload);

// ok: deserialization-unserialize-package-call
require('some-other-package')(payload);
