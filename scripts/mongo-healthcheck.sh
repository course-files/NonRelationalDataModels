#!/bin/bash
# Starts the one-member replica set the first time, then reports READY once
# this node is the writable primary. (Transactions need a replica set.)
mongosh --quiet --eval "
try { rs.status(); }
catch (e) { rs.initiate({_id: 'rs0', members: [{_id: 0, host: 'mongo:27017'}]}); }
print(db.hello().isWritablePrimary ? 'READY' : 'WAIT');
" 2>/dev/null | grep -q READY
