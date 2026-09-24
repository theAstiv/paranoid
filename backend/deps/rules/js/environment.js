// ruleid: environment-json-stringify-env
fetch(url, { body: JSON.stringify(process.env) });

// ok: environment-json-stringify-env
JSON.stringify({ NODE_ENV: process.env.NODE_ENV });

// ruleid: environment-env-spread
const payload = { ...process.env };

// ok: environment-env-spread
const payload2 = { NODE_ENV: process.env.NODE_ENV };
