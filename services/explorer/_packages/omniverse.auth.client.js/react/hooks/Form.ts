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

import { useCallback, useMemo, useRef, useState } from "react";
import useMounted from "./Mounted";

export interface FormSettings<F, T> {
  fields: F;
  onStart?: FormStartCallback<F>;
  onFail?: FormFailCallback;
  onSuccess?: FormSuccessCallback<T>;
  onSubmit: FormSubmitCallback<F, T>;
  onCancel?: FormCancelCallback;
}

export type FormStartCallback<F> = (fields: F) => boolean;
export type FormFailCallback = (errors: string[]) => void;
export type FormSuccessCallback<T> = (result: T) => void;
export type FormSubmitCallback<F, T> = (fields: F) => Promise<T | FormErrors>;
export type FormCancelCallback = () => void;
export type FormErrors = {
  errors?: string[];
};

export default function useForm<F, T>({
  fields: formFields,
  onStart,
  onSuccess,
  onFail,
  onSubmit,
  onCancel,
}: FormSettings<F, T>) {
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [result, setResult] = useState<T | null>(null);

  const fields = useRef<F>(formFields);
  fields.current = formFields;

  const mounted = useMounted();

  const callbacks = useRef({
    onStart,
    onSuccess,
    onFail,
    onSubmit,
    onCancel,
  });
  callbacks.current = { onStart, onSuccess, onFail, onSubmit, onCancel };

  const submit = useCallback(async () => {
    const { onStart, onSuccess, onFail, onSubmit } = callbacks.current;

    setLoading(true);
    setErrors([]);
    setResult(null);

    try {
      if (onStart) {
        const proceed = onStart(fields.current);
        if (!proceed) {
          return;
        }
      }

      const result = await onSubmit(fields.current);
      const errors = (result as FormErrors)?.errors;

      if (!mounted.current) {
        return;
      }

      setLoading(false);
      if (errors?.length) {
        setErrors(errors);
        if (onFail) {
          onFail(errors);
        }
      } else {
        setResult(result as T);
        if (onSuccess) {
          onSuccess(result as T);
        }
      }
    } catch (e) {
      if (mounted.current) {
        setLoading(false);
        setErrors([e instanceof Error ? e.message : (e as Object).toString()]);
      }

      if (process.env.NODE_ENV !== "test") {
        console.error(e);
      }
    }
  }, [mounted]);

  const cancel = useCallback(() => {
    const { onCancel } = callbacks.current;
    setLoading(false);
    if (onCancel) {
      onCancel();
    }
  }, []);

  return useMemo(
    () => ({
      fields: fields.current,
      result,
      submit,
      cancel,
      loading,
      setLoading,
      errors,
      setErrors,
    }),
    [loading, result, errors, submit, cancel]
  );
}
