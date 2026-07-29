export class Stepper {
    constructor({ steps, container, onStepChange }) {
        this.steps = steps;
        this.container = container;
        this.onStepChange = onStepChange || (() => {});
        this.currentIndex = 0;
    }

    get currentStep() {
        return this.steps[this.currentIndex];
    }

    goTo(stepKey) {
        const index = this.steps.indexOf(stepKey);
        if (index === -1) return;
        this.currentIndex = index;
        this._render();
    }

    next() {
        if (this.currentIndex < this.steps.length - 1) {
            this.currentIndex += 1;
            this._render();
        }
    }

    back() {
        if (this.currentIndex > 0) {
            this.currentIndex -= 1;
            this._render();
        }
    }

    init() {
        this._render();
    }

    _render() {
        this.container.querySelectorAll('[data-step-panel]').forEach((panel) => {
            panel.style.display = panel.dataset.stepPanel === this.currentStep ? 'block' : 'none';
        });
        this.container.querySelectorAll('[data-progress-step]').forEach((node) => {
            const stepIndex = this.steps.indexOf(node.dataset.progressStep);
            node.classList.toggle('active', stepIndex === this.currentIndex);
            node.classList.toggle('completed', stepIndex < this.currentIndex);
        });
        this.onStepChange(this.currentStep);
    }
}
