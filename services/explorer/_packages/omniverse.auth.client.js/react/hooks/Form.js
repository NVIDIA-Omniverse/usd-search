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

var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
var __generator = (this && this.__generator) || function (thisArg, body) {
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g;
    return g = { next: verb(0), "throw": verb(1), "return": verb(2) }, typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
    function verb(n) { return function (v) { return step([n, v]); }; }
    function step(op) {
        if (f) throw new TypeError("Generator is already executing.");
        while (_) try {
            if (f = 1, y && (t = op[0] & 2 ? y["return"] : op[0] ? y["throw"] || ((t = y["return"]) && t.call(y), 0) : y.next) && !(t = t.call(y, op[1])).done) return t;
            if (y = 0, t) op = [op[0] & 2, t.value];
            switch (op[0]) {
                case 0: case 1: t = op; break;
                case 4: _.label++; return { value: op[1], done: false };
                case 5: _.label++; y = op[1]; op = [0]; continue;
                case 7: op = _.ops.pop(); _.trys.pop(); continue;
                default:
                    if (!(t = _.trys, t = t.length > 0 && t[t.length - 1]) && (op[0] === 6 || op[0] === 2)) { _ = 0; continue; }
                    if (op[0] === 3 && (!t || (op[1] > t[0] && op[1] < t[3]))) { _.label = op[1]; break; }
                    if (op[0] === 6 && _.label < t[1]) { _.label = t[1]; t = op; break; }
                    if (t && _.label < t[2]) { _.label = t[2]; _.ops.push(op); break; }
                    if (t[2]) _.ops.pop();
                    _.trys.pop(); continue;
            }
            op = body.call(thisArg, _);
        } catch (e) { op = [6, e]; y = 0; } finally { f = t = 0; }
        if (op[0] & 5) throw op[1]; return { value: op[0] ? op[1] : void 0, done: true };
    }
};
import { useCallback, useMemo, useRef, useState } from "react";
import useMounted from "./Mounted";
export default function useForm(_a) {
    var _this = this;
    var formFields = _a.fields, onStart = _a.onStart, onSuccess = _a.onSuccess, onFail = _a.onFail, onSubmit = _a.onSubmit, onCancel = _a.onCancel;
    var _b = useState(false), loading = _b[0], setLoading = _b[1];
    var _c = useState([]), errors = _c[0], setErrors = _c[1];
    var _d = useState(null), result = _d[0], setResult = _d[1];
    var fields = useRef(formFields);
    fields.current = formFields;
    var mounted = useMounted();
    var callbacks = useRef({
        onStart: onStart,
        onSuccess: onSuccess,
        onFail: onFail,
        onSubmit: onSubmit,
        onCancel: onCancel,
    });
    callbacks.current = { onStart: onStart, onSuccess: onSuccess, onFail: onFail, onSubmit: onSubmit, onCancel: onCancel };
    var submit = useCallback(function () { return __awaiter(_this, void 0, void 0, function () {
        var _a, onStart, onSuccess, onFail, onSubmit, proceed, result_1, errors_1, e_1;
        var _b;
        return __generator(this, function (_c) {
            switch (_c.label) {
                case 0:
                    _a = callbacks.current, onStart = _a.onStart, onSuccess = _a.onSuccess, onFail = _a.onFail, onSubmit = _a.onSubmit;
                    setLoading(true);
                    setErrors([]);
                    setResult(null);
                    _c.label = 1;
                case 1:
                    _c.trys.push([1, 3, , 4]);
                    if (onStart) {
                        proceed = onStart(fields.current);
                        if (!proceed) {
                            return [2 /*return*/];
                        }
                    }
                    return [4 /*yield*/, onSubmit(fields.current)];
                case 2:
                    result_1 = _c.sent();
                    errors_1 = (_b = result_1) === null || _b === void 0 ? void 0 : _b.errors;
                    if (!mounted.current) {
                        return [2 /*return*/];
                    }
                    setLoading(false);
                    if (errors_1 === null || errors_1 === void 0 ? void 0 : errors_1.length) {
                        setErrors(errors_1);
                        if (onFail) {
                            onFail(errors_1);
                        }
                    }
                    else {
                        setResult(result_1);
                        if (onSuccess) {
                            onSuccess(result_1);
                        }
                    }
                    return [3 /*break*/, 4];
                case 3:
                    e_1 = _c.sent();
                    if (mounted.current) {
                        setLoading(false);
                        setErrors([e_1 instanceof Error ? e_1.message : e_1.toString()]);
                    }
                    if (process.env.NODE_ENV !== "test") {
                        console.error(e_1);
                    }
                    return [3 /*break*/, 4];
                case 4: return [2 /*return*/];
            }
        });
    }); }, [mounted]);
    var cancel = useCallback(function () {
        var onCancel = callbacks.current.onCancel;
        setLoading(false);
        if (onCancel) {
            onCancel();
        }
    }, []);
    return useMemo(function () { return ({
        fields: fields.current,
        result: result,
        submit: submit,
        cancel: cancel,
        loading: loading,
        setLoading: setLoading,
        errors: errors,
        setErrors: setErrors,
    }); }, [loading, result, errors, submit, cancel]);
}
