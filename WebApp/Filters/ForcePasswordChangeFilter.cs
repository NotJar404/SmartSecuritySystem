using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Filters;

namespace SmartSecuritySystem.Filters
{
    /// <summary>
    /// Global action filter that forces users with MustChangePassword claim
    /// to the Profile page. They cannot access ANY other page until they
    /// change their temporary password.
    /// 
    /// Exempt controllers: Auth (login/logout), Profile (password change target)
    /// </summary>
    public class ForcePasswordChangeFilter : IActionFilter
    {
        public void OnActionExecuting(ActionExecutingContext context)
        {
            var user = context.HttpContext.User;

            // Only apply to authenticated users with the MustChangePassword claim
            if (!user.Identity?.IsAuthenticated ?? true)
                return;

            if (!user.HasClaim("MustChangePassword", "true"))
                return;

            // Allow access to Profile and Auth controllers (exempt)
            var controller = context.RouteData.Values["controller"]?.ToString();

            if (string.Equals(controller, "Profile", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(controller, "Auth", StringComparison.OrdinalIgnoreCase))
                return;

            // Block ALL other controllers — redirect to Profile
            context.Result = new RedirectToActionResult("Index", "Profile", null);
        }

        public void OnActionExecuted(ActionExecutedContext context)
        {
            // No post-action logic needed
        }
    }
}
