import { useRef, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router';
import { useAuth } from '../auth/useAuth';
import AuthCard from '../components/AuthCard';
import { btn, focusRing } from '../components/classes';
import { Field, PasswordField } from '../components/FormField';
import { ErrorBanner, Spinner } from '../components/ui';
import { MIN_PASSWORD, passwordStrength, validateEmail, validatePassword } from '../lib/validation';

const link = `rounded font-medium text-fg underline decoration-line-strong underline-offset-4 hover:decoration-accent ${focusRing}`;

function StrengthHint({ value }) {
  const { score, label } = passwordStrength(value);
  if (!value) return <span>At least {MIN_PASSWORD} characters. Mix letters, numbers and symbols for a stronger password.</span>;
  return (
    <span className="flex items-center gap-2">
      <span className="flex gap-1" aria-hidden="true">
        {[1, 2, 3, 4].map((i) => (
          <span key={i} className={`h-1 w-6 rounded-full ${i <= score ? 'bg-fg-secondary' : 'bg-line-strong'}`} />
        ))}
      </span>
      <span>Strength: {label}</span>
    </span>
  );
}

export default function Signup() {
  const { register, startDemo, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [values, setValues] = useState({ name: '', email: '', password: '', confirm: '' });
  const [errors, setErrors] = useState({});
  const [serverError, setServerError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const nameRef = useRef(null);
  const emailRef = useRef(null);
  const passwordRef = useRef(null);
  const confirmRef = useRef(null);

  if (isAuthenticated && !submitting) return <Navigate to="/upload" replace />;

  const validators = {
    name: (v) => (v.trim().length > 100 ? 'Keep your name under 100 characters.' : ''),
    email: validateEmail,
    password: (v) => validatePassword(v, { signup: true }),
    confirm: (v, all) => (!v ? 'Confirm your password.' : v !== all.password ? 'Passwords don’t match.' : ''),
  };
  const validate = (name, all = values) => validators[name](all[name], all);

  const setField = (name) => (e) => {
    const all = { ...values, [name]: e.target.value };
    setValues(all);
    if (errors[name]) setErrors((s) => ({ ...s, [name]: validate(name, all) }));
  };
  const onBlur = (name) => () => setErrors((s) => ({ ...s, [name]: validate(name) }));

  const onSubmit = async (e) => {
    e.preventDefault();
    const next = Object.fromEntries(Object.keys(validators).map((k) => [k, validate(k)]));
    setErrors(next);
    const firstBad = Object.keys(next).find((k) => next[k]);
    if (firstBad) {
      ({ name: nameRef, email: emailRef, password: passwordRef, confirm: confirmRef })[firstBad].current?.focus();
      return;
    }
    setSubmitting(true);
    setServerError(null);
    try {
      await register({ name: values.name.trim(), email: values.email.trim(), password: values.password });
      navigate('/upload', { replace: true });
    } catch (err) {
      setServerError(err);
      setSubmitting(false);
    }
  };

  const enterDemo = () => {
    startDemo();
    navigate('/upload', { replace: true });
  };

  return (
    <AuthCard
      title="Create your account"
      subtitle="Upload a match video and see every player’s numbers."
      footer={
        <>
          Already have an account?{' '}
          <Link to="/login" state={location.state} className={link}>
            Log in
          </Link>
        </>
      }
    >
      {serverError && (
        <ErrorBanner
          className="mb-5"
          title={serverError.isNetwork ? 'Backend not reachable' : 'Could not create your account'}
          onRetry={serverError.isNetwork ? enterDemo : undefined}
          retryLabel="Explore with sample data"
        >
          {serverError.status === 409 ? 'An account with that email already exists. Try logging in.' : serverError.message}
        </ErrorBanner>
      )}
      <form noValidate onSubmit={onSubmit} className="space-y-4">
        <Field label="Name (optional)" name="name" autoComplete="name" inputRef={nameRef} value={values.name} onChange={setField('name')} onBlur={onBlur('name')} error={errors.name} />
        <Field
          label="Email"
          name="email"
          type="email"
          inputMode="email"
          autoComplete="email"
          inputRef={emailRef}
          value={values.email}
          onChange={setField('email')}
          onBlur={onBlur('email')}
          error={errors.email}
          required
        />
        <PasswordField
          label="Password"
          name="password"
          autoComplete="new-password"
          inputRef={passwordRef}
          value={values.password}
          onChange={setField('password')}
          onBlur={onBlur('password')}
          error={errors.password}
          hint={<StrengthHint value={values.password} />}
          required
        />
        <PasswordField
          label="Confirm password"
          name="confirm"
          autoComplete="new-password"
          inputRef={confirmRef}
          value={values.confirm}
          onChange={setField('confirm')}
          onBlur={onBlur('confirm')}
          error={errors.confirm}
          required
        />
        <button type="submit" disabled={submitting} className={`${btn.primary} h-11 w-full`}>
          {submitting ? (
            <>
              <Spinner /> Creating account…
            </>
          ) : (
            'Create account'
          )}
        </button>
      </form>
    </AuthCard>
  );
}
