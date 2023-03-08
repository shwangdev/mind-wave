#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (C) 2022 Andy Stewart
#
# Author:     Andy Stewart <lazycat.manatee@gmail.com>
# Maintainer: Andy Stewart <lazycat.manatee@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
import queue
import threading
import traceback
import os
import sys
import base64
from pathlib import Path
from epc.server import ThreadingEPCServer
from utils import (init_epc_client, eval_in_emacs, logger, close_epc_client, get_emacs_func_result, message_emacs)

class MindWave:
    def __init__(self, args):
        # Init EPC client port.
        init_epc_client(int(args[0]))

        # Build EPC server.
        self.server = ThreadingEPCServer(('localhost', 0), log_traceback=True)
        # self.server.logger.setLevel(logging.DEBUG)
        self.server.allow_reuse_address = True

        # ch = logging.FileHandler(filename=os.path.join(mind-wave_config_dir, 'epc_log.txt'), mode='w')
        # formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(lineno)04d | %(message)s')
        # ch.setFormatter(formatter)
        # ch.setLevel(logging.DEBUG)
        # self.server.logger.addHandler(ch)
        # self.server.logger = logger

        self.server.register_instance(self)  # register instance functions let elisp side call

        # Start EPC server with sub-thread, avoid block Qt main loop.
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.start()

        # Pass epc port and webengine codec information to Emacs when first start mind-wave.
        eval_in_emacs('mind-wave--first-start', self.server.server_address[1])

        # All Emacs request running in event_loop.
        self.event_queue = queue.Queue()
        self.event_loop = threading.Thread(target=self.event_dispatcher)
        self.event_loop.start()

        # All LSP server response running in message_thread.
        self.message_queue = queue.Queue()
        self.message_thread = threading.Thread(target=self.message_dispatcher)
        self.message_thread.start()

        # Build thread queue.
        self.thread_queue = []

        # event_loop never exit, simulation event loop.
        self.event_loop.join()

    def event_dispatcher(self):
        try:
            while True:
                message = self.event_queue.get(True)

                print(message)

                self.event_queue.task_done()
        except:
            logger.error(traceback.format_exc())

    def message_dispatcher(self):
        try:
            while True:
                message = self.message_queue.get(True)

                print(message)

                self.message_queue.task_done()
        except:
            logger.error(traceback.format_exc())

    def chat_get_api_key(self):
        user_emacs_dir = get_emacs_func_result("get-user-emacs-directory")
        mind_wave_dir = os.path.join(user_emacs_dir, "mind-wave")
        mind_wave_chat_api_key_file_path = os.path.join(mind_wave_dir, "chatgpt_api_key.txt")
        if os.path.exists(mind_wave_chat_api_key_file_path):
            with open(mind_wave_chat_api_key_file_path, "r") as f:
                api_key = f.read().strip()
                if api_key != "":
                    return api_key

        message_emacs("ChatGPT API key not exist, please copy it from https://platform.openai.com/account/api-keys, and fill API key in file: {}".format(
            mind_wave_chat_api_key_file_path))

        return None

    def chat_ask(self, buffer_file_name, buffer_content, promt):
        api_key = self.chat_get_api_key()
        if api_key is not None:
            completion_thread = threading.Thread(target=lambda: self.chat_completion(api_key, buffer_file_name, buffer_content, promt))
            completion_thread.start()
            self.thread_queue.append(completion_thread)

    def chat_completion(self, api_key, buffer_file_name, buffer_content, promt):
        content = self.chat_parse_content(buffer_content)
        import openai

        openai.api_key = api_key
        response = openai.ChatCompletion.create(
            model = "gpt-3.5-turbo",
            messages = content + [{"role": "user", "content": promt}])

        result = ''
        for choice in response.choices:
            result += choice.message.content

        eval_in_emacs("mind-wave-chat-answer", buffer_file_name, result, response.usage.total_tokens)

    def chat_parse_content(self, buffer_content):
        text = base64.b64decode(buffer_content).decode("utf-8")

        messages = []

        lines = text.split('\n')  # split the text into lines
        role = ''  # initialize the role
        content = ''  # initialize the content

        for line in lines:
            if line.startswith('------ '):
                if role:  # output the content of the previous role
                    messages.append({ "role": role, "content": content })
                role = line.strip('------ ').strip().lower()  # get the current role
                content = ''  # reset the content for the current role
            else:
                content += line  # append the line to the content for the current role

        # output the content of the last role
        if role:
            messages.append({ "role": role, "content": content })

        default_system = {"role": "system", "content": "You are a helpful assistant."}
        if len(messages) == 0:
            messages.append(default_system)
        elif messages[0]["role"] != "system":
            messages = [default_system] + messages

        return messages

    def cleanup(self):
        """Do some cleanup before exit python process."""
        close_epc_client()

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        import cProfile
        profiler = cProfile.Profile()
        profiler.run("MindWave(sys.argv[1:])")
    else:
        MindWave(sys.argv[1:])
