/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import React, { useEffect, useState } from "react";
import { Redirect } from "react-router-dom";
import DeviceCodeStatus from "./DeviceCodeStatus";
import Form from "./Form";
import FormError from "./FormError";
import FormSpinner from "./FormSpinner";
import { useDeviceFlowSubmit } from "./hooks/DeviceFlow";
import useNucleusSession from "./hooks/NucleusSession";
import NvidiaLogo from "./NvidiaLogo";
import OmniverseLogo from "./OmniverseLogo";
var DeviceCodeSubmit = function (_a) {
    var code = _a.code;
    var _b = useState(true), loading = _b[0], setLoading = _b[1];
    var _c = useState(null), status = _c[0], setStatus = _c[1];
    var _d = useState(""), error = _d[0], setError = _d[1];
    var session = useNucleusSession();
    var submitUserCode = useDeviceFlowSubmit();
    useEffect(function () {
        submitUserCode({ code: code })
            .then(function (result) { return setStatus(result.status); })
            .catch(function (error) { return setError(error.message || error.toString()); })
            .finally(function () { return setLoading(false); });
    }, [code, submitUserCode]);
    if (!session.established) {
        return React.createElement(Redirect, { to: "/" });
    }
    return (React.createElement(Form, null,
        React.createElement(NvidiaLogo, null),
        React.createElement(OmniverseLogo, null),
        React.createElement(DeviceCodeSubmitBody, { loading: loading, status: status, error: error })));
};
var DeviceCodeSubmitBody = function (_a) {
    var loading = _a.loading, status = _a.status, error = _a.error;
    if (loading) {
        return React.createElement(FormSpinner, null);
    }
    if (error) {
        return React.createElement(FormError, null, error);
    }
    return React.createElement(DeviceCodeStatus, { status: status });
};
export default DeviceCodeSubmit;
