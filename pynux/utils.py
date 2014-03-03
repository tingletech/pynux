#!/usr/bin/env python
# -*- coding: utf8 -*-

"""
pynux.utils
~~~~~~~~~~~

python function library for working with nuxeo "REST" APIs.

"""

import requests
import json
import sys
import os
import time
import itertools


class Nuxeo:
    def __init__(self, conf={}):
        """configuration for http connections"""
        # http://stackoverflow.com/a/17501381/1763984
        defaults = {
            "user":
            os.environ.get('NUXEO_API_USER',
                           "Administrator"),
            "password":
            os.environ.get('NUXEO_API_PASS',
                           "Administrator"),
            "api":
            os.environ.get('NUXEO_REST_API',
                           "http://localhost:8080/nuxeo/site/api/v1"),
            "fileImporter":
            os.environ.get('NUXEO_FILEIMPORTER_API',
                           "http://localhost:8080/nuxeo/site/fileImporter")
        }
        self.conf = {}
        self.conf.update(defaults)
        self.conf.update(conf)
        self.auth = (self.conf["user"], self.conf["password"])

    def _get_page(self, url, params, current_page_index):
        """get a single page of nuxeo API results"""
        params.update({'currentPageIndex': current_page_index})
        res = requests.get(url, params=params, auth=self.auth)
        res.raise_for_status()
        return json.loads(res.text)

    def _get_iter(self, url, params):
        """generator iterator for nuxeo results"""
        for current_page_index in itertools.count():
            result_dict = self._get_page(url, params, current_page_index)
            for document in result_dict['entries']:
                yield document
            if not result_dict['isNextPageAvailable']:
                break

    #
    ######## utility functions for nuxeo

    # REST API

    def nxql(self, query):
        """generice nxql query"""
        url = os.path.join(self.conf["api"], "path/@search")
        params = {
            'pageSize': '100',
            'query': query
        }
        return self._get_iter(url, params)

    def all(self):
        """.nxql("SELECT * FROM Document")"""
        return self.nxql('SELECT * FROM Document')

    def children(self, path):
        """get child documents of a path"""
        url = os.path.join(self.conf["api"], "path",
                           path.strip("/"), "@children")
        params = {}
        return self._get_iter(url, params)

    def get_uid(self, path):
        """look up uid from the path"""
        url = os.path.join(self.conf['api'],  "path",
                           path.strip("/"))
        res = requests.get(url, auth=self.auth)
        res.raise_for_status()
        return json.loads(res.text)['uid']

    def get_metadata(self, **documentid):
        """get metadata for a `uid` or `path` parameter"""
        if len(documentid) != 1:
            raise TypeError("either uid or path")
        url = ""
        if 'path' in documentid:
            url = os.path.join(self.conf['api'], "path",
                               documentid['path'].strip("/"))
        elif 'uid' in documentid:
            url = os.path.join(self.conf['api'], "id", documentid['uid'])
        else:
            raise Exception("no document id found")
        headers = {'X-NXDocumentProperties': 'ucldc_schema,dublincore'}
        res = requests.get(url, headers=headers, auth=self.auth)
        res.raise_for_status()
        return json.loads(res.text)

    def update_nuxeo_properties(self, data, **documentid):
        """update nuxeo document properties, `uid=` or `path=` parameter"""
        uid = ''
        if len(documentid) != 1:
            raise TypeError("either uid or path")
        if 'path' in documentid:
            uid = self.get_uid(documentid['path'])
        elif 'uid' in documentid:
            uid = documentid['uid']
        url = os.path.join(self.conf['api'], "id", uid)
        # TODO: let headers be specified, use these as defaults
        headers = {'X-NXDocumentProperties': 'ucldc_schema,dublincore',
                   'Content-Type': 'application/json+nxentity'}
        # copy what we want from the input json into the payload
        payload = {}
        payload['uid'] = uid
        payload['properties'] = data['properties']
        res = requests.put(url,
                           data=json.dumps(payload),
                           auth=self.auth,
                           headers=headers)
        res.raise_for_status()
        return json.loads(res.text)

    def print_document_summary(self, documents):
        for document in documents:
            print "{0}\t{1}".format(document['uid'], document['path'])

    def copy_metadata_to_local(self, documents, local):
        for document in documents:
            path = document['path']
            path = path.strip("/")
            file = os.path.join(local, ''.join([path.strip("/"), ".json"]))
            dir = os.path.dirname(file)
            self._mkdir(dir)
            with open(file, 'w') as json_file:
                py_json = self.get_metadata(path=path)
                out_json = {}
                out_json['uid'] = py_json['uid']
                out_json['path'] = py_json['path']
                out_json["entity-type"] = py_json["entity-type"]
                out_json['properties'] = py_json['properties']
                json_file.write(json.dumps(out_json,
                                           sort_keys=True,
                                           indent=4,
                                           separators=(',', ': ')))

    # platform importer api

    def call_file_importer_api(self, verb, params={}):
        """generic wrapper to make GET calls to this API"""
        url = "{0}/{1}".format(self.conf['fileImporter'], verb)
        res = requests.get(url, params=params, auth=self.auth)
        res.raise_for_status()
        return res.text

    def import_log(self):
        """show small part of file importer log"""
        print self.call_file_importer_api("log")

    def import_log_activate(self):
        """activate file importer log"""
        print self.call_file_importer_api("logActivate")

    def import_one_folder(self,
                          leaf_type, input_path, target_path, folderish_type, wait=True):
        """trigger an import and wait for it to finish"""
        if not leaf_type and input_path and target_path and folderish_type:
            raise TypeError("missing required value")
        params = {
            "leafType": leaf_type,
            "inputPath": input_path,
            "targetPath": target_path,
            "folderishType": folderish_type,
        }
        # only one import can run at a time
        self.import_status_wait(wait=wait)
        print self.call_file_importer_api("run", params)
        # an import should now be running
        self.import_status_wait(wait=wait)
        return

    def import_status_wait(self, wait=True, sleep=20):
        """check import status and wait for Not Running"""
        if not wait:     # for the impatient
            return True
        # poll the api to and wait for the run to finish...
        url = "{0}/{1}".format(self.conf['fileImporter'], "status")
        res = requests.get(url, auth=self.auth)
        res.raise_for_status()
        if res.text == 'Not Running':
            return True
        else:
            time.sleep(sleep)
            sys.stdout.write('.')
            sys.stdout.flush()
            self.import_status_wait()

    #
    ## utility functions
    #
    def _mkdir(self, newdir):
        """works the way a good mkdir should :)
            - already exists, silently complete
            - regular file in the way, raise an exception
            - parent directory(ies) does not exist, make them as well
        """
        # http://code.activestate.com/recipes/82465-a-friendly-mkdir/
        if os.path.isdir(newdir):
            pass
        elif os.path.isfile(newdir):
            raise OSError("a file with the same name as the desired "
                          "dir, '%s', already exists." % newdir)
        else:
            head, tail = os.path.split(newdir)
            if head and not os.path.isdir(head):
                self._mkdir(head)
            #print "_mkdir %s" % repr(newdir)
            if tail:
                os.mkdir(newdir)

def test():
    """ Testing Docstring"""
    pass

if __name__ == '__main__':
    test()

"""
Copyright © 2014, Regents of the University of California
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

- Redistributions of source code must retain the above copyright notice,
  this list of conditions and the following disclaimer.
- Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.
- Neither the name of the University of California nor the names of its
  contributors may be used to endorse or promote products derived from this
  software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
"""
