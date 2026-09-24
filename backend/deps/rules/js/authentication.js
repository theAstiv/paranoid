// ruleid: authentication-jsonwebtoken-sign-or-verify
require('jsonwebtoken').sign(payload, secret);

const jwt = require('jsonwebtoken');
// ruleid: authentication-jsonwebtoken-sign-or-verify
jwt.verify(token, secret);

const { sign } = require('jsonwebtoken');
// ruleid: authentication-jsonwebtoken-sign-or-verify
sign(payload, secret);

const notJwt = require('some-other-lib');
// ok: authentication-jsonwebtoken-sign-or-verify
notJwt.sign(payload, secret);

// ruleid: authentication-password-hash-call
require('bcrypt').hash(password, 10);

const bcrypt = require('bcryptjs');
// ruleid: authentication-password-hash-call
bcrypt.compareSync(password, hash);

const { hash } = require('argon2');
// ruleid: authentication-password-hash-call
hash(password);

// ruleid: authentication-passport-strategy-use
require('passport').use(new LocalStrategy(verifyFn));

const passport = require('passport');
// ruleid: authentication-passport-strategy-use
passport.use(new LocalStrategy(verifyFn));

const notPassport = require('some-other-lib');
// ok: authentication-passport-strategy-use
notPassport.use(strategy);

// ruleid: authentication-set-authorization-header
headers['Authorization'] = `Bearer ${token}`;

// ruleid: authentication-set-authorization-header
headers.set("Authorization", `Bearer ${token}`);

// ok: authentication-set-authorization-header
headers['Content-Type'] = 'application/json';
