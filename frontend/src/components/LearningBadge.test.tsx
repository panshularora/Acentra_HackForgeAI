import { render, screen } from '@testing-library/react';
import { LearningBadge } from './LearningBadge';

describe('LearningBadge', () => {
  it('shows baseline progress while learning', () => {
    const { container } = render(
      <LearningBadge state={{ kind: 'learning', collected: 4, required: 6 }} />,
    );
    const badge = container.querySelector('.learning-badge');
    expect(badge).toHaveClass('learning-badge--learning');
    expect(badge).toHaveTextContent('Detector: Learning baseline, 4 of 6 buckets');
    expect(badge).toHaveAttribute('title', expect.stringMatching(/alerts start once/));
  });

  it('shows monitoring with the template count once ready', () => {
    render(<LearningBadge state={{ kind: 'ready', templates: 38 }} />);
    expect(screen.getByText('Monitoring, 38 templates')).toHaveClass('learning-badge--monitoring');
  });

  it('labels the first-window phase with the configured window', () => {
    render(
      <LearningBadge state={{ kind: 'filling', collected: 2, required: 6 }} windowSeconds={120} />,
    );
    expect(screen.getByText(/Filling first 120s window, 2 of 6 buckets/)).toHaveClass(
      'learning-badge--learning',
    );
  });

  it('never uses severity styling', () => {
    const { container } = render(<LearningBadge state={{ kind: 'waiting' }} />);
    expect(container.innerHTML).not.toMatch(/severity|warning|critical|high/i);
  });
});
