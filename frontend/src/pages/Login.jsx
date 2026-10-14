import { useRef, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router';
import { useAuth } from '../auth/useAuth';
import AuthCard from '../components/AuthCard';
import { btn, focusRing } from '../components/classes';
import { Field, PasswordField } from '../components/FormField';
import { ErrorBanner, Spinner } from '../components/ui';
import { validateEmail, validatePassword } from '../lib/validation';

const link = `rounded font-medium text-fg underline decoration-line-strong underline-offset-4 hover:decoration-accent ${focusRing}`;

export default function Login() {
  const { login, startDemo, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from || '/profile';

  const [values, setValues] = useState({ email: '', password: '' });
  const [errors, setErrors] = useState({});
  const [serverError, setServerError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const emailRef = useRef(null);
  const passwordRef = useRef(null);

  if (isAuthenticated && !submitting) return <Navigate to={from} replace />;

  const validators = { email: validateEmail, password: (v) => validatePassword(v) };
  const setField = (name) => (e) => {
    const v = e.target.value;
    setValues((s) => ({ ...s, [name]: v }));
    if (errors[name]) setErrors((s) => ({ ...s, [name]: validators[name](v) }));
  };
  const onBlur = (name) => () => setErrors((s) => ({ ...s, [name]: validators[name](values[name]) }));

  const onSubmit = async (e) => {
    e.preventDefault();
    const next = { email: validateEmail(values.email), password: validatePassword(values.password) };
    setErrors(next);
    const firstBad = Object.keys(next).find((k) => next[k]);
    if (firstBad) {
      ({ email: emailRef, password: passwordRef })[firstBad].current?.focus();
      return;
    }
    setSubmitting(true);
    setServerError(null);
    try {
      await login(values.email.trim(), values.password);
      navigate(from, { replace: true });
    } catch (err) {
      setServerError(err);
      setSubmitting(false);
    }
  };

  const enterDemo = () => {
    startDemo();
    navigate(from, { replace: true });
  };

  return (
    <AuthCard
      title="Welcome back"
      subtitle="Log in to upload matches and view your results."
      footer={
        <>
          New here?{' '}
          <Link to="/signup" state={location.state} className={link}>
            Create an account
          </Link>
        </>
      }
    >
      {serverError && (
        <ErrorBanner
          className="mb-5"
          title={serverError.isNetwork ? 'Backend not reachable' : 'Could not log you in'}
          onRetry={serverError.isNetwork ? enterDemo : undefined}
          retryLabel="Explore with sample data"
        >
          {serverError.status === 401 ? 'Incorrect email or password.' : serverError.message}
        </ErrorBanner>
      )}
      <form noValidate onSubmit={onSubmit} className="space-y-4">
        <Field
          label="Email"
          name="email"
          type="email"
          autoComplete="email"
          inputMode="email"
          inputRef={emailRef}
          value={values.email}
          onChange={setField('email')}
          onBlur={onBlur('email')}
          error={errors.email}
          required
        />
        <div>
          <PasswordField
            label="Password"
            name="password"
            autoComplete="current-password"
            inputRef={passwordRef}
            value={values.password}
            onChange={setField('password')}
            onBlur={onBlur('password')}
            error={errors.password}
            required
          />
          <div className="mt-2 text-right">
            <Link to="/forgot-password" className={`text-caption text-fg-muted hover:text-fg ${focusRing} rounded`}>
              Forgot password?
            </Link>
          </div>
        </div>
        <button type="submit" disabled={submitting} className={`${btn.primary} h-11 w-full`}>
          {submitting ? (
            <>
              <Spinner /> Signing in…
            </>
          ) : (
            'Log in'
          )}
        </button>
      </form>
    </AuthCard>
  );
}
