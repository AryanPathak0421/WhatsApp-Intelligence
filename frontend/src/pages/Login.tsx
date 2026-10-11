import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Navigate, useLocation } from 'react-router-dom';
import { z } from 'zod';
import { Button, Field, Input } from '../components/ui';
import { apiError } from '../lib/api';
import { useAuth } from '../lib/auth';

const schema = z.object({ email: z.string().email('Enter a valid email'), password: z.string().min(1, 'Enter your password') });

export default function Login() {
  const { user, login } = useAuth();
  const loc = useLocation();
  const [error, setError] = useState('');
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema) });
  if (user) return <Navigate to={(loc.state as any)?.from ?? '/'} replace />;
  return (
    <div className="grid min-h-full place-items-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <div className="grid size-11 place-items-center rounded-xl bg-brand-600 text-lg font-bold text-white">PI</div>
          <h1 className="text-xl font-semibold">Project Intelligence</h1><p className="muted text-sm">Team chat that turns project conversations into structured insight.</p>
        </div>
        <form className="card space-y-4 p-6" noValidate onSubmit={handleSubmit(async (v) => {
          setError('');
          try { await login(v.email, v.password); } catch (e) { setError(apiError(e).message); }
        })}>
          {error && <div role="alert" className="rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-400">{error}</div>}
          <Field label="Email" error={errors.email?.message}><Input type="email" autoComplete="username" autoFocus {...register('email')} /></Field>
          <Field label="Password" error={errors.password?.message}><Input type="password" autoComplete="current-password" {...register('password')} /></Field>
          <Button type="submit" variant="primary" className="w-full" loading={isSubmitting}>Sign in</Button>
        </form>
        <p className="muted mt-4 text-center text-xs">Your chat data is processed on your own infrastructure. No external AI services.</p>
      </div>
    </div>
  );
}
