// ruleid: crypto-node-crypto-call
require('crypto').createHash('sha256').update(data).digest('hex');

// ruleid: crypto-node-crypto-call
require('node:crypto').randomBytes(16);

const crypto1 = require('crypto');
// ruleid: crypto-node-crypto-call
crypto1.createCipheriv('aes-256-gcm', key, iv);

var crypto2 = require("crypto");
// ruleid: crypto-node-crypto-call
crypto2.createHmac('sha256', secret);

// TypeScript CommonJS emit for `import { createHash } from 'crypto'`
const crypto_1 = require("crypto");
// ruleid: crypto-node-crypto-call
(0, crypto_1.createHash)('md5');

// TypeScript emit for `import crypto from 'crypto'` (esModuleInterop)
const crypto_2 = __importDefault(require("crypto"));
// ruleid: crypto-node-crypto-call
crypto_2.default.randomBytes(32);

const { createSign, createVerify } = require('crypto');
// ruleid: crypto-node-crypto-call
createSign('RSA-SHA256');
// ruleid: crypto-node-crypto-call
createVerify('RSA-SHA256');

import cryptoDefault from 'node:crypto';
// ruleid: crypto-node-crypto-call
cryptoDefault.generateKeyPairSync('rsa', opts);

import * as cryptoNs from 'crypto';
// ruleid: crypto-node-crypto-call
cryptoNs.pbkdf2Sync(pw, salt, 100000, 64, 'sha512');

import { scrypt } from 'crypto';
// ruleid: crypto-node-crypto-call
scrypt(pw, salt, 64, cb);

import { scrypt as kdf } from 'crypto';
// todoruleid: crypto-node-crypto-call
kdf(pw, salt, 64, cb);

const notCrypto = require('some-crypto-lib');
// ok: crypto-node-crypto-call
notCrypto.createHash('sha256');

// Passed by reference rather than called directly.
const crypto3 = require('crypto');
// ruleid: crypto-node-crypto-call
const hashAsync = util.promisify(crypto3.pbkdf2);

// ruleid: crypto-webcrypto-subtle
crypto.subtle.digest('SHA-256', data);

// ruleid: crypto-webcrypto-subtle
crypto.subtle.encrypt(alg, key, data);

// ok: crypto-webcrypto-subtle
myCustomObject.subtle.digest('SHA-256', data);
