#!/usr/bin/env python
# Copyright 2019 Nokia
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import re
import shutil
import hashlib
import lxml.html
import urllib3


HTTP = urllib3.PoolManager()

def debug(log):
    print(log)

def verbose(log):
    print(log)

def filter_dot(lst):
    return filter(lambda path: path[0] != '.', lst)

def get_url(url, file_hash):
    debug("http get {}".format(url))
    request = HTTP.request('GET', url)
    dom = lxml.html.fromstring(request.data)
    for link in filter_dot(dom.xpath('//a/@href')):
        path = '{}/{}'.format(url, link)
        debug("http get {}".format(path))
        request = HTTP.request('GET', path)
        dom = lxml.html.fromstring(request.data)
        if file_hash in dom.xpath('//a/@href'):
            return '{}{}'.format(path, file_hash)

def get_repo_name(path):
    regex = re.compile(r'^\.([^.]*).metadata$')
    meta = list(filter(regex.match, os.listdir(path)))
    if len(meta) == 0:
        return None
    if len(meta) != 1:
        raise Exception('Multiple metadata files: {}'.format(", ".join(meta)))
    repo_name = regex.search(meta[0]).group(1)
    debug("repo name is {}".format(repo_name))
    return repo_name

def parse_metadatafile(path, repo_name):
    result = {}
    filename = "{}/.{}.metadata".format(path, repo_name)
    debug("metadata file: {}".format(filename))
    with open(filename) as metadata:
        for line in metadata:
            items = line.split()
            result[items[1]] = items[0]
            debug('found {}: {}'.format(items[1], items[0]))
    return result

def get_hash(filename, hashfunc):
    with open(filename, 'rb', buffering=0) as contents:
        for buffer in iter(lambda: contents.read(128*1024), b''):
            hashfunc.update(buffer)
    digest = hashfunc.hexdigest()
    debug("digest is {}".format(digest))
    return digest

def check_file(filename, checksum):
    debug("checking {} {}".format(filename, checksum))
    hashmap = {
        32  : hashlib.md5(),
        40  : hashlib.sha1(),
        64  : hashlib.sha256(),
        128 : hashlib.sha512()
    }
    if len(checksum) not in hashmap:
        raise Exception('Checksum lenght unsupported: {}'.format(checksum))
    if get_hash(filename, hashmap[len(checksum)]) != checksum:
        raise Exception("Checksum doesn't match: {} {}".format(filename, checksum))
    debug("checksum ok")

def download(url, destination, checksum):
    tmpfile = "{}.tmp".format(destination)
    try:
        debug("downloading {} to {}".format(url, tmpfile))
        with HTTP.request('GET', url, preload_content=False) as resp, open(tmpfile, 'wb') as out_file:
            shutil.copyfileobj(resp, out_file)
        check_file(tmpfile, checksum)
        debug("renaming {} to {}".format(tmpfile, destination))
        os.rename(tmpfile, destination)
    finally:
        try:
            os.remove(tmpfile)
            debug("removed {}".format(tmpfile))
        except OSError:
            pass

def get_sources(path, sources_list, logger):
    if logger:
        global debug
        global verbose
        debug = logger.debug
        verbose = logger.info

    repo = get_repo_name(path)
    if not repo:
        verbose('no metadata file in "{}".'.format(path))
        return

    for k, v in parse_metadatafile(path, repo).items():
        filename = os.path.join(path, k)
        try:
            check_file(filename, v)
        except:
            found = False
            for sources in sources_list:
                repo_root = "{}/{}".format(sources, repo)
                url = get_url(repo_root, v)
                if url:
                    debug("retrieving {} to {}".format(url, filename))
                    download(url, filename, v)
                    verbose('retrieved "{}"'.format(k))
                    found = True
                    break
            if not found:
                raise Exception('File "{}" not found'.format(v))
