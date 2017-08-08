#!/usr/bin/env pytho3
import pickle

userdict={}
with open( '/opt/icingateller/registry/31799909/31799909', 'rb' ) as f:
	userdict = pickle.load( f )

print( userdict )

