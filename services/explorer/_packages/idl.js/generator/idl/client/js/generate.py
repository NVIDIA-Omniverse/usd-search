# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
from os.path import abspath, dirname, join, realpath

import idl.client.js.filters
import idl.schema.asymmetric
import idl.templates.filters.capabilities
from idl.parser import parse
from idl.templates.renderer import Renderer, copy, mkdir

script_path = abspath(dirname(realpath(__file__)))
template_path = join(script_path, "templates")


def generate_js_client(
    src: str,
    dest: str,
    package_name: str,
    package_version: str = None,
    copyright_path: str = None,
):
    spec = parse(src, processors=[idl.schema.asymmetric.processor(client=True)])
    mkdir(dest)

    asymmetric_context = {"asymmetric": {"client": True}}

    copyright_text = []
    if copyright_path:
        print(f"Copyright file: {copyright_path}")
        with open(copyright_path) as copyright_file:
            copyright_text = copyright_file.readlines()

    renderer = Renderer(spec, template_path)
    renderer.include_filters(idl.client.js.filters)
    renderer.include_filters(idl.templates.filters.capabilities)
    renderer.render(
        "data.txt",
        join(dest, "data.js"),
        {**asymmetric_context, "copyright": copyright_text},
    )
    renderer.render(
        "data.d.ts.txt",
        join(dest, "data.d.ts"),
        {**asymmetric_context, "copyright": copyright_text},
    )
    renderer.render("client.txt", join(dest, "client.js"), {"copyright": copyright_text})
    renderer.render("client.d.ts.txt", join(dest, "client.d.ts"), {"copyright": copyright_text})
    renderer.render(
        "package.txt",
        join(dest, "package.json"),
        {"package_name": package_name, "package_version": package_version},
    )
    copy(join(template_path, "LICENSE.txt"), join(dest, "LICENSE.txt"))


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-s",
        "--src",
        "--spec",
        dest="src",
        type=str,
        required=True,
        help="Path to IDL JSON.",
    )
    parser.add_argument(
        "-d",
        "--dest",
        "--out",
        dest="dest",
        type=str,
        required=True,
        help="Output file.",
    )
    parser.add_argument(
        "--copyright",
        dest="copyright_path",
        type=str,
        required=False,
        help="Path to the file with the copyright text.",
    )
    parser.add_argument("--name", dest="package_name", type=str, required=True, help="Package name.")
    parser.add_argument(
        "--version",
        dest="package_version",
        type=str,
        required=False,
        help="Package version.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    generate_js_client(
        args.src,
        args.dest,
        args.package_name,
        args.package_version,
        args.copyright_path,
    )
