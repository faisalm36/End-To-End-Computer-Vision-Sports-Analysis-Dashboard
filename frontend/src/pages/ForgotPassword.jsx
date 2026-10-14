import { Link } from 'react-router';
import AuthCard from '../components/AuthCard';
import { btn } from '../components/classes';

// Placeholder until the backend exposes a password-reset endpoint.
export default function ForgotPassword() {
  return (
    <AuthCard title="Reset your password" subtitle="Password reset by email isn’t available yet.">
      <p className="text-body text-fg-secondary">
        Contact the project team to reset your password. This page will send a reset link once the backend supports it.
      </p>
      <Link to="/login" className={`${btn.secondary} mt-6 w-full`}>
        Back to log in
      </Link>
    </AuthCard>
  );
}
