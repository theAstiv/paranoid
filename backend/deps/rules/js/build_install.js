// ruleid: build-install-dynamic-require
require(moduleNameFromEnv);

// ruleid: build-install-dynamic-require
require(`./plugins/${pluginName}`);

// ok: build-install-dynamic-require
require('lodash');

// ok: build-install-dynamic-require
require("./local-helper");
