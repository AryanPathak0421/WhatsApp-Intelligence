import { useQueryClient } from '@tanstack/react-query';
import { Download, FileSpreadsheet, FileText, FileJson, Table2 } from 'lucide-react';
import { useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Field, Input, PageHeader, Select, TableSkeleton, Td, Th, useToast } from '../components/ui';
import { api, apiError } from '../lib/api';
import { useAuth } from '../lib/auth';
import { fmtDateTime } from '../lib/format';
import { useReports } from '../lib/queries';

export default function Reports() {
  const { projectId } = useOutletContext<{ projectId?: string }>();
  const { can } = useAuth();
  const { data, isLoading, error, refetch } = useReports(projectId);
  const [kind, setKind] = useState('FULL'); const [company, setCompany] = useState(''); const [busy, setBusy] = useState(false);
  const qc = useQueryClient(); const toast = useToast();
  if (!projectId) return <EmptyState title="Select a project first" />;

  const generate = async () => {
    setBusy(true);
    try { await api.post(`/projects/${projectId}/reports/generate`, { kind, company: company || undefined }); await qc.invalidateQueries({ queryKey: ['reports'] }); toast.push('success', 'Report generated'); }
    catch (e) { toast.push('error', apiError(e).message); } finally { setBusy(false); }
  };
  const download = async (id: string, format: string) => {
    try {
      const r = await api.get(`/reports/${id}`, { params: { format }, responseType: format === 'json' ? 'json' : 'blob' });
      const blob = format === 'json' ? new Blob([JSON.stringify(r.data.content, null, 2)], { type: 'application/json' }) : r.data;
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `report-${id.slice(0, 8)}.${format}`; a.click(); URL.revokeObjectURL(a.href);
    } catch (e) { toast.push('error', apiError(e).message); }
  };
  return (
    <>
      <PageHeader title="Reports" sub="A complete A-to-Z project report, ready to send to management." />
      {can('report:generate') && (
        <Card className="mb-5"><CardHeader title="Generate a report" sub="Includes executive summary, KPIs, tasks, contribution, client pending, risks, timeline and recommendations." />
          <div className="flex flex-wrap items-end gap-3 px-5 pb-5">
            <div className="w-40"><Field label="Type"><Select value={kind} onChange={(e) => setKind(e.target.value)}><option value="FULL">Full report</option><option value="DAILY">Daily</option><option value="WEEKLY">Weekly</option></Select></Field></div>
            <div className="w-64"><Field label="Company name (on the cover)"><Input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="Acme Tech" /></Field></div>
            <Button variant="primary" loading={busy} onClick={generate}>Generate</Button></div></Card>)}
      <Card className="overflow-hidden"><CardHeader title="Generated reports" />
        {isLoading ? <TableSkeleton rows={3} cols={4} /> : error ? <ErrorState error={error} onRetry={refetch} /> : !data?.length ? <EmptyState title="No reports yet" hint="Generate your first report above." /> : (
          <div className="overflow-x-auto"><table className="w-full min-w-[560px]"><thead className="border-y bg-[var(--surface-2)]/50"><tr><Th>Generated</Th><Th>Type</Th><Th>Download</Th></tr></thead>
            <tbody className="divide-y">{data.map((r) => (
              <tr key={r.id}><Td>{fmtDateTime(r.createdAt)}</Td><Td><Badge>{r.kind.toLowerCase()}</Badge></Td>
                <Td><div className="flex flex-wrap gap-1.5">
                  <Button size="sm" onClick={() => download(r.id, 'pdf')}><FileText className="size-3.5" />PDF</Button><Button size="sm" onClick={() => download(r.id, 'xlsx')}><FileSpreadsheet className="size-3.5" />Excel</Button>
                  <Button size="sm" onClick={() => download(r.id, 'csv')}><Table2 className="size-3.5" />CSV</Button><Button size="sm" onClick={() => download(r.id, 'json')}><FileJson className="size-3.5" />JSON</Button></div></Td></tr>))}</tbody></table></div>)}
      </Card>
      <p className="muted mt-3 flex items-center gap-1.5 text-xs"><Download className="size-3.5" />Exports include message ids, so every figure can be traced back to the original chat. Manual task corrections are not yet reflected in generated reports.</p>
    </>
  );
}
