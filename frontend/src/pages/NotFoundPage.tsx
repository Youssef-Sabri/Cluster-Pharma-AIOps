import { Link } from 'react-router-dom';
import { Card } from '@/components/ui/Card';

export function NotFoundPage() {
  return (
    <Card title="404">
      <p className="muted" style={{ marginBottom: 'var(--space-4)' }}>
        That route is not part of the ClusterOps console.
      </p>
      <Link to="/">Return to the operations overview</Link>
    </Card>
  );
}

export default NotFoundPage;