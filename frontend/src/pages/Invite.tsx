import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Button, Field, Input, Skeleton } from '../components/ui';
import { api, apiError, tokens } from '../lib/api';

interface InviteInfo { email: string; name: string | null; roomName: string; projectName: string | null; inviterName: string; expiresAt: string; accountExists: boolean }

/** Public page behind the e-mail link: shows who invited you to which group, and creates your account. */
export default function Invite() {
  const { token = '' } = useParams();
  const { data, error, isLoading } = useQuery({ queryKey: ['invite', token], retry: false, queryFn: () => api.get<InviteInfo>(`/invites/${token}`).then((r) => r.data) });
  const [name, setName] = useState('');
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const shownName = name || data?.name || '';

  const accept = async () => {
    setErr('');
    if (pw.length < 10) return setErr('Password must be at least 10 characters.');
    if (pw !== pw2) return setErr('The two passwords do not match.');
    setBusy(true);
    try {
      const r = await api.post(`/invites/${token}/accept`, { name: shownName.trim(), password: pw });
      tokens.set(r.data.accessToken, r.data.refreshToken);
      window.location.assign(`/chat/${r.data.roomId}`);                                   // full load so the session starts cleanly
    } catch (e) { setErr(apiError(e).message); setBusy(false); }
  };

  return (
    <div className="grid min-h-full place-items-center p-4" style={{ background: '#f0f2f5' }}>
      <div className="w-full max-w-md overflow-hidden rounded-xl bg-white shadow-sm" style={{ color: '#111b21' }}>
        <div className="px-6 py-4 text-lg font-semibold text-white" style={{ background: '#00a884' }}>Group invitation</div>
        <div className="space-y-4 p-6">
          {isLoading && <Skeleton className="h-24" />}
          {error && (
            <div className="space-y-3">
              <p className="text-sm">{apiError(error).message}</p>
              <Link to="/login" className="text-sm font-medium" style={{ color: '#00a884' }}>Go to sign in</Link>
            </div>)}
          {data && (
            <>
              <p className="text-[15px]"><b>{data.inviterName}</b> invited you to the group <b>{data.roomName}</b>{data.projectName ? <> for the project <b>{data.projectName}</b></> : null}.</p>
              {data.accountExists ? (
                <div className="space-y-2 text-sm">
                  <p>An account with {data.email} already exists. Sign in, and ask the group admin to add you.</p>
                  <Link to="/login" className="font-medium" style={{ color: '#00a884' }}>Sign in</Link>
                </div>
              ) : (
                <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void accept(); }}>
                  <Field label="E-mail"><Input value={data.email} disabled /></Field>
                  <Field label="Your name"><Input value={shownName} onChange={(e) => setName(e.target.value)} required maxLength={100} autoComplete="name" /></Field>
                  <Field label="Choose a password (at least 10 characters)"><Input type="password" value={pw} onChange={(e) => setPw(e.target.value)} required autoComplete="new-password" /></Field>
                  <Field label="Repeat the password"><Input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} required autoComplete="new-password" /></Field>
                  {err && <p className="text-sm text-red-600" role="alert">{err}</p>}
                  <Button type="submit" variant="primary" loading={busy} disabled={!shownName.trim()} className="w-full">Accept and join</Button>
                  <p className="text-xs" style={{ color: '#667781' }}>The link works once and expires on {new Date(data.expiresAt).toLocaleDateString()}.</p>
                </form>
              )}
            </>)}
        </div>
      </div>
    </div>
  );
}
