#!/usr/bin/env python

import os, sys
import hashlib

def md5_file_as_bytes(filepath):
    with open(filepath, 'rb') as file:
        bytes = file.read()
    return hashlib.md5(bytes).hexdigest()


def gather():
    for dir in os.listdir():
        def join(f):
            return os.path.join(dir, f)
        try:
            with open(join('contract_filename.txt')) as f:
                name = f.readline().split('/')[-1].split('_')[0]
            print('?', name, '.temp/'+join('contract.hex'), '.temp/'+join('out/get_source.py.out'))
        except FileNotFoundError:
            pass


if __name__ == '__main__':
    gather()

