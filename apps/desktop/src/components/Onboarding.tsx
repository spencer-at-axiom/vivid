import type { Model, PromptingConfig } from "../lib/types";

export interface OnboardingProps {
  activeModel: Model | null;
  promptingConfig: PromptingConfig | null;
  onSelectIntent: (intentId: string) => void;
}

export default function Onboarding({ activeModel, promptingConfig, onSelectIntent }: OnboardingProps) {
  if (!promptingConfig) {
    return (
      <div className="onboarding">
        <h1>Welcome to Vivid Studio</h1>
        <p>Loading starter flows and prompt defaults...</p>
      </div>
    );
  }

  return (
    <div className="onboarding">
      <h1>Welcome to Vivid Studio</h1>
      <p>Pick a starting lane. Vivid will preload the prompt stack and, when a local model is available, fire the first generation immediately.</p>
      <div className="intent-grid">
        {promptingConfig.starter_intents.map((intent) => {
          const activeMatchesRecommendation =
            activeModel?.id != null &&
            (intent.recommended_model_ids.includes(activeModel.id) || activeModel.family === intent.recommended_model_family);

          return (
            <button
              key={intent.id}
              className="intent-card"
              onClick={() => onSelectIntent(intent.id)}
              type="button"
            >
              <strong>{intent.title}</strong>
              <span>{intent.description}</span>
              <p className="setting-description">{intent.starter_prompt}</p>
              <p className="setting-description">Recommended model family: {intent.recommended_model_family.toUpperCase()}</p>
              <p className="setting-description">
                {activeMatchesRecommendation && activeModel
                  ? `Current local model selected: ${activeModel.name}`
                  : `Recommended path: ${intent.recommended_model_ids[0] ?? intent.recommended_model_family.toUpperCase()}`}
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
