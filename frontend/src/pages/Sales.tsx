import { useOutletContext } from 'react-router-dom';
import { Card, EmptyState, ErrorState, PageHeader, TableSkeleton, Td, Th } from '../components/ui';
import { useSales } from '../lib/queries';

export default function Sales() {
  const { projectId } = useOutletContext<{ projectId?: string }>();
  const { data, isLoading, error, refetch } = useSales(projectId);
  if (!projectId) return <EmptyState title="Select a project first" />;
  return (
    <>
      <PageHeader title="Sales activity" sub="Follow-ups, payment discussions and what is still waiting on the client." />
      <Card className="overflow-hidden">
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : !data?.length ? <EmptyState title="No sales people detected" hint="Names containing “Sales” are detected automatically; you can also set a role on the Team page." /> : (
          <div className="overflow-x-auto"><table className="w-full min-w-[720px]"><thead className="border-b bg-[var(--surface-2)]/50"><tr><Th>Salesperson</Th><Th>Client follow-ups</Th><Th>Resolved</Th><Th>Pending</Th><Th>Payment discussions</Th><Th>Proposals</Th><Th>Escalations</Th></tr></thead>
            <tbody className="divide-y">{data.map((s) => (
              <tr key={s.person}><Td className="font-medium">{s.person}</Td><Td>{s.client_follow_ups}</Td><Td>{s.follow_ups_resolved}</Td>
                <Td className={s.follow_ups_pending ? 'font-semibold text-amber-600 dark:text-amber-400' : ''}>{s.follow_ups_pending}</Td><Td>{s.payment_discussions}</Td><Td>{s.proposals}</Td><Td>{s.escalations}</Td></tr>))}</tbody></table></div>)}
      </Card>
    </>
  );
}
