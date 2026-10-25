import { provideHttpClient, withFetch, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding, withNavigationErrorHandler, withRouterConfig } from '@angular/router';
import { routes } from './app.routes';
import { authInterceptor } from './core/auth';
import { loadingInterceptor } from './core/loading';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideHttpClient(withFetch(), withInterceptors([authInterceptor, loadingInterceptor])),
    provideRouter(routes, withComponentInputBinding(), withRouterConfig({ paramsInheritanceStrategy: 'always' }),
      // a page opened before the app was rebuilt asks for screen files that no longer exist: load the new build instead
      withNavigationErrorHandler((e) => {
        if (/dynamically imported module|Loading chunk|Importing a module script failed/i.test(String(e.error?.message ?? e.error))) {
          location.assign(e.url);
        }
      })),
  ],
};
