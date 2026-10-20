import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { Layout } from '@/components/layout/Layout';
import { HomePage } from '@/pages/HomePage';
import { InventoryPage } from '@/pages/InventoryPage';
import { NewOrderPage } from '@/pages/NewOrderPage';
import { OrderHistoryPage } from '@/pages/OrderHistoryPage';
import { ApprovalsPage } from '@/pages/ApprovalsPage';
import { AdminPage } from '@/pages/AdminPage';
import { NotFoundPage } from '@/pages/NotFoundPage';

/**
 * Route table.
 *
 * Six product routes named for what the operator does, not for what the backend
 * exposes. Everything is nested under `Layout`, so the shell is mounted once and
 * navigation never remounts it.
 *
 * `/admin` is the only route that carries technical telemetry, and it is
 * deliberately absent from the primary navigation.
 */
export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route path="inventory" element={<InventoryPage />} />
        <Route path="orders/new" element={<NewOrderPage />} />
        <Route path="orders" element={<OrderHistoryPage />} />
        <Route path="approvals" element={<ApprovalsPage />} />
        <Route path="admin" element={<AdminPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

export function Root() {
  return (
    <BrowserRouter>
      <App />
    </BrowserRouter>
  );
}

export default Root;
